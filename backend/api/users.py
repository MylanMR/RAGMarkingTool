"""Account administration (admin role). Attributes set here are what the PDP
evaluates; changes are hash-chain logged and revoke the user's sessions."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.api.auth import user_out
from backend.auth import passwords, sessions
from backend.auth.deps import Principal, require_roles
from backend.db.database import get_session
from backend.governance import chain
from backend.models.governance import ROLES, User
from backend.models.marking import MarkingError
from backend.policy import catalog, store as policy_store
from backend.retrieval.pdp import UserAttributes

router = APIRouter(prefix="/users", tags=["users"])


class UserIn(BaseModel):
    username: str = Field(..., min_length=1, max_length=128)
    display_name: str = Field(..., min_length=1)
    auth_source: str = "local"
    initial_password: Optional[str] = None
    roles: List[str]
    clearance: str
    citizenship: str
    compartments: List[str] = Field(default_factory=list)
    need_to_know_groups: List[str] = Field(default_factory=list)


class UserPatch(BaseModel):
    display_name: Optional[str] = None
    roles: Optional[List[str]] = None
    clearance: Optional[str] = None
    citizenship: Optional[str] = None
    compartments: Optional[List[str]] = None
    need_to_know_groups: Optional[List[str]] = None
    active: Optional[bool] = None


class ResetIn(BaseModel):
    new_password: str


def validate_roles_and_attrs(db: Session, username: str, roles: List[str], clearance: str,
                             citizenship: str, compartments: List[str], ntk: List[str]) -> None:
    bad = [r for r in roles if r not in ROLES]
    if bad or not roles:
        raise HTTPException(status_code=422,
                            detail="roles must be a non-empty subset of {}".format(list(ROLES)))
    policy = policy_store.current(db)
    if "admin" in roles and "ao" in roles and policy.get("role_separation") == "separate":
        raise HTTPException(status_code=422, detail=(
            "AO policy requires separate admin and AO accounts "
            "(Administrator and AO role separation)"))
    try:
        UserAttributes(user_id=username, clearance=clearance, citizenship=citizenship,
                       compartments=compartments, need_to_know_groups=ntk)
    except MarkingError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if catalog.level_rank(clearance.upper()) > catalog.level_rank(policy.system_high):
        raise HTTPException(status_code=422, detail=(
            "clearance {} exceeds the system high ({}) set in policy"
            .format(clearance, policy.system_high)))


def create_user(db: Session, payload: UserIn, actor: str) -> User:
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=409, detail="username already exists")
    if payload.auth_source not in ("local", "ad", "oidc", "saml"):
        raise HTTPException(status_code=422, detail="unknown auth_source")
    validate_roles_and_attrs(db, payload.username, payload.roles, payload.clearance,
                             payload.citizenship, payload.compartments,
                             payload.need_to_know_groups)
    pw_hash = None
    if payload.auth_source == "local":
        try:
            passwords.check_policy(payload.initial_password or "", payload.username)
        except passwords.PasswordPolicyError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        pw_hash = passwords.hash_password(payload.initial_password)
    user = User(username=payload.username, display_name=payload.display_name,
                auth_source=payload.auth_source, password_hash=pw_hash,
                roles=sorted(set(payload.roles)), clearance=payload.clearance.upper(),
                citizenship=payload.citizenship.upper(), compartments=payload.compartments,
                need_to_know_groups=payload.need_to_know_groups, active=True,
                failed_attempts=0, must_change_password=payload.auth_source == "local")
    db.add(user)
    db.flush()
    chain.record(db, actor=actor, event_type="user.created", subject_type="user",
                 subject_id=user.id, payload={k: v for k, v in user_out(user).items()})
    return user


@router.get("")
def list_users(p: Principal = Depends(require_roles("admin", "auditor")),
               db: Session = Depends(get_session)) -> list:
    return [user_out(u) for u in db.query(User).order_by(User.username).all()]


@router.post("", status_code=201)
def add_user(payload: UserIn, p: Principal = Depends(require_roles("admin")),
             db: Session = Depends(get_session)) -> dict:
    user = create_user(db, payload, p.user.username)
    db.commit()
    return user_out(user)


@router.patch("/{user_id}")
def edit_user(user_id: str, payload: UserPatch, p: Principal = Depends(require_roles("admin")),
              db: Session = Depends(get_session)) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    changes = payload.model_dump(exclude_none=True)
    if user.id == p.id and ("roles" in changes or changes.get("active") is False):
        raise HTTPException(status_code=422,
                            detail="administrators cannot change their own roles or disable themselves")
    merged = dict(roles=changes.get("roles", user.roles),
                  clearance=changes.get("clearance", user.clearance),
                  citizenship=changes.get("citizenship", user.citizenship),
                  compartments=changes.get("compartments", user.compartments),
                  ntk=changes.get("need_to_know_groups", user.need_to_know_groups))
    validate_roles_and_attrs(db, user.username, merged["roles"], merged["clearance"],
                             merged["citizenship"], merged["compartments"], merged["ntk"])
    before = user_out(user)
    for k, v in changes.items():
        if k in ("clearance", "citizenship"):
            v = v.upper()
        if k == "roles":
            v = sorted(set(v))
        setattr(user, k, v)
    sessions.revoke_all(db, user.id)
    chain.record(db, actor=p.user.username, event_type="user.updated", subject_type="user",
                 subject_id=user.id, payload={"before": before, "changes": changes})
    db.commit()
    return user_out(user)


@router.post("/{user_id}/unlock")
def unlock(user_id: str, p: Principal = Depends(require_roles("admin")),
           db: Session = Depends(get_session)) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    user.locked_until = None
    user.failed_attempts = 0
    chain.record(db, actor=p.user.username, event_type="user.unlocked", subject_type="user",
                 subject_id=user.id, payload={})
    db.commit()
    return user_out(user)


@router.post("/{user_id}/reset-password")
def reset_password(user_id: str, payload: ResetIn, p: Principal = Depends(require_roles("admin")),
                   db: Session = Depends(get_session)) -> dict:
    user = db.get(User, user_id)
    if user is None or user.auth_source != "local":
        raise HTTPException(status_code=404, detail="local user not found")
    try:
        passwords.check_policy(payload.new_password, user.username)
    except passwords.PasswordPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    user.password_hash = passwords.hash_password(payload.new_password)
    user.must_change_password = True
    user.locked_until = None
    sessions.revoke_all(db, user.id)
    chain.record(db, actor=p.user.username, event_type="user.password_reset",
                 subject_type="user", subject_id=user.id, payload={})
    db.commit()
    return user_out(user)
