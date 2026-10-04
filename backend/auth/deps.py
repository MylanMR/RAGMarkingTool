"""FastAPI dependencies: resolve the bearer token to a Principal and enforce
roles. In scaffold mode (dev only) unauthenticated requests are allowed on
the Phase 1-5 endpoints so the original tests and UI keep working."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Set

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend import config
from backend.auth import sessions
from backend.db.database import get_session
from backend.models.governance import User
from backend.retrieval.pdp import UserAttributes


@dataclass
class Principal:
    user: User
    roles: Set[str]

    @property
    def id(self) -> str:
        return self.user.id

    @property
    def label(self) -> str:
        return "{} ({})".format(self.user.username, self.user.id)

    def attributes(self) -> UserAttributes:
        u = self.user
        return UserAttributes(user_id=u.username, clearance=u.clearance,
                              citizenship=u.citizenship,
                              compartments=list(u.compartments or []),
                              need_to_know_groups=list(u.need_to_know_groups or []))


def _bearer(request: Request) -> Optional[str]:
    h = request.headers.get("authorization", "")
    if h.lower().startswith("bearer "):
        return h[7:].strip() or None
    return None


def optional_principal(request: Request, db: Session = Depends(get_session)) -> Optional[Principal]:
    token = _bearer(request)
    if not token:
        return None
    user = sessions.resolve(db, token)
    db.commit()
    if user is None:
        raise HTTPException(status_code=401, detail="session expired or invalid")
    return Principal(user=user, roles=set(user.roles or []))


def require_principal(p: Optional[Principal] = Depends(optional_principal)) -> Principal:
    if p is None:
        raise HTTPException(status_code=401, detail="sign-in required")
    return p


def require_roles(*roles: str) -> Callable:
    def dep(p: Principal = Depends(require_principal)) -> Principal:
        if not p.roles.intersection(roles):
            raise HTTPException(status_code=403,
                                detail="requires role: {}".format(" or ".join(roles)))
        return p
    return dep


def scaffold_or_roles(*roles: str) -> Callable:
    """Phase 1-5 endpoints: open in dev scaffold mode, role-gated otherwise."""
    def dep(p: Optional[Principal] = Depends(optional_principal)) -> Optional[Principal]:
        if p is None:
            if config.auth_mode() == config.AUTH_MODE_SCAFFOLD:
                return None
            raise HTTPException(status_code=401, detail="sign-in required")
        if not p.roles.intersection(roles):
            raise HTTPException(status_code=403,
                                detail="requires role: {}".format(" or ".join(roles)))
        return p
    return dep
