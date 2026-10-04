"""Local sign-in, sign-out, and password change. Responses never reveal
whether a username exists; lockout follows the AO policy threshold."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.auth import ad, passwords, sessions
from backend.auth.deps import Principal, _bearer, require_principal
from backend.db.database import get_session
from backend.governance import chain
from backend.models.governance import User
from backend.policy import store as policy_store

router = APIRouter(prefix="/auth", tags=["auth"])
LOCK_MINUTES = 15


class LoginIn(BaseModel):
    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=1, max_length=1024)


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str


def user_out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "display_name": u.display_name,
            "auth_source": u.auth_source, "roles": list(u.roles or []),
            "clearance": u.clearance, "citizenship": u.citizenship,
            "compartments": list(u.compartments or []),
            "need_to_know_groups": list(u.need_to_know_groups or []),
            "active": u.active, "must_change_password": u.must_change_password,
            "locked": bool(u.locked_until and _aware(u.locked_until) > _now())}


def _now():
    return datetime.now(timezone.utc)


def _aware(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@router.post("/login")
def login(payload: LoginIn, db: Session = Depends(get_session)) -> dict:
    fail = HTTPException(status_code=401, detail="invalid username or password")
    user = db.query(User).filter(User.username == payload.username.strip()).first()
    if user is None or user.auth_source != "local" or not user.password_hash:
        passwords.verify_password(payload.password, passwords.DUMMY_HASH)
        raise fail
    if not user.active:
        passwords.verify_password(payload.password, passwords.DUMMY_HASH)
        raise fail
    if user.locked_until and _aware(user.locked_until) > _now():
        chain.record(db, actor=user.username, event_type="auth.login_locked",
                     subject_type="user", subject_id=user.id, payload={})
        db.commit()
        raise HTTPException(status_code=423,
                            detail="account locked; try again later or contact an administrator")
    if not passwords.verify_password(payload.password, user.password_hash):
        threshold = int(policy_store.current(db).get("lockout_threshold"))
        user.failed_attempts = (user.failed_attempts or 0) + 1
        event = "auth.login_failed"
        if user.failed_attempts >= threshold:
            user.locked_until = _now() + timedelta(minutes=LOCK_MINUTES)
            user.failed_attempts = 0
            event = "auth.account_locked"
        chain.record(db, actor=user.username, event_type=event, subject_type="user",
                     subject_id=user.id, payload={})
        db.commit()
        raise fail
    user.failed_attempts = 0
    user.locked_until = None
    token, expires = sessions.create(db, user)
    chain.record(db, actor=user.username, event_type="auth.login", subject_type="user",
                 subject_id=user.id, payload={})
    db.commit()
    return {"token": token, "expires_at": expires.isoformat(), "user": user_out(user)}


@router.post("/logout")
def logout(request: Request, p: Principal = Depends(require_principal),
           db: Session = Depends(get_session)) -> dict:
    sessions.revoke(db, _bearer(request))
    chain.record(db, actor=p.user.username, event_type="auth.logout", subject_type="user",
                 subject_id=p.id, payload={})
    db.commit()
    return {"status": "signed out"}


@router.get("/me")
def me(p: Principal = Depends(require_principal)) -> dict:
    return user_out(p.user)


@router.post("/password")
def change_password(payload: PasswordChangeIn, request: Request,
                    p: Principal = Depends(require_principal),
                    db: Session = Depends(get_session)) -> dict:
    user = db.get(User, p.id)
    if user.auth_source != "local" or not passwords.verify_password(
            payload.current_password, user.password_hash or ""):
        raise HTTPException(status_code=400, detail="current password is incorrect")
    try:
        passwords.check_policy(payload.new_password, user.username)
    except passwords.PasswordPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    user.password_hash = passwords.hash_password(payload.new_password)
    user.must_change_password = False
    sessions.revoke_all(db, user.id)
    token, expires = sessions.create(db, user)
    chain.record(db, actor=user.username, event_type="auth.password_changed",
                 subject_type="user", subject_id=user.id, payload={})
    db.commit()
    return {"token": token, "expires_at": expires.isoformat(), "user": user_out(user)}


@router.get("/providers")
def providers() -> dict:
    """Which sign-in methods the login page should offer."""
    return {"local": True, "ad": ad.enabled(), "oidc": False, "saml": False}


def _ad_user(db: Session, username: str) -> User:
    """Resolve an authenticated AD identity to a tool account."""
    user = db.query(User).filter(User.username == username).first()
    if user is not None and user.auth_source != "ad":
        raise ad.ADAuthError("{} is a {} account; AD sign-in cannot use it"
                             .format(username, user.auth_source))
    if ad.attribute_source() == "tool":
        if user is None:
            raise ad.ADAuthError("no tool account for AD user {}".format(username))
        return user
    # directory mode: attributes and roles come from AD on every sign-in
    from backend.api.users import validate_roles_and_attrs
    prof = ad.directory_lookup(username)
    try:
        validate_roles_and_attrs(db, username, prof.roles, prof.clearance, prof.citizenship,
                                 prof.compartments, prof.need_to_know_groups)
    except HTTPException as exc:
        raise ad.ADAuthError("directory attributes rejected: {}".format(exc.detail)) from None
    new = {"display_name": prof.display_name, "roles": prof.roles, "clearance": prof.clearance,
           "citizenship": prof.citizenship, "compartments": prof.compartments,
           "need_to_know_groups": prof.need_to_know_groups}
    if user is None:
        user = User(username=username, auth_source="ad", password_hash=None, active=True,
                    failed_attempts=0, must_change_password=False, **new)
        db.add(user)
        db.flush()
        chain.record(db, actor="directory", event_type="user.provisioned", subject_type="user",
                     subject_id=user.id, payload=dict(new, groups=prof.groups))
        return user
    if not user.active:
        raise ad.ADAuthError("tool account {} is disabled".format(username))
    old = {k: getattr(user, k) for k in new}
    if old != new:
        for k, v in new.items():
            setattr(user, k, v)
        chain.record(db, actor="directory", event_type="user.directory_sync", subject_type="user",
                     subject_id=user.id, payload={"before": old, "after": new,
                                                  "groups": prof.groups})
    return user


@router.get("/negotiate")
def negotiate(request: Request, db: Session = Depends(get_session)):
    """Windows Integrated Authentication (Kerberos only)."""
    if not ad.enabled():
        raise HTTPException(status_code=404, detail="Active Directory sign-in is not enabled")
    header = request.headers.get("authorization", "")
    challenge = JSONResponse(status_code=401, content={"detail": "Windows sign-in required"},
                             headers={"WWW-Authenticate": "Negotiate"})
    if not header.lower().startswith("negotiate "):
        return challenge
    try:
        username, mutual = ad.accept(header)
        user = _ad_user(db, username)
        if not user.active:
            raise ad.ADAuthError("tool account {} is disabled".format(username))
    except (ad.ADAuthError, ValueError) as exc:
        db.rollback()
        chain.record(db, actor="ad", event_type="auth.ad_refused", subject_type="auth",
                     subject_id="negotiate", payload={"reason": str(exc)})
        db.commit()
        return JSONResponse(status_code=403, content={
            "detail": "Windows sign-in was refused. Contact your administrator."})
    token, expires = sessions.create(db, user)
    chain.record(db, actor=user.username, event_type="auth.login", subject_type="user",
                 subject_id=user.id, payload={"method": "kerberos"})
    db.commit()
    headers = {"WWW-Authenticate": "Negotiate " + mutual} if mutual else {}
    return JSONResponse(content={"token": token, "expires_at": expires.isoformat(),
                                 "user": user_out(user)}, headers=headers)
