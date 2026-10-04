"""Server-side sessions. The browser holds an opaque bearer token in memory;
the database stores only its SHA-256, so a database read cannot replay a
session. Idle timeout comes from the AO policy; absolute lifetime from config."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from backend import config
from backend.models.governance import AuthSession, User
from backend.policy import store as policy_store


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create(db: Session, user: User) -> Tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    now = _now()
    expires = now + timedelta(hours=config.session_absolute_hours())
    db.add(AuthSession(token_hash=_hash(token), user_id=user.id, created_at=now,
                       last_seen=now, expires_at=expires))
    db.flush()
    return token, expires


def resolve(db: Session, token: str) -> Optional[User]:
    row = db.get(AuthSession, _hash(token))
    if row is None:
        return None
    now = _now()
    idle = int(policy_store.current(db).get("session_idle_minutes"))
    if _aware(row.expires_at) <= now or _aware(row.last_seen) + timedelta(minutes=idle) <= now:
        db.delete(row)
        db.flush()
        return None
    user = db.get(User, row.user_id)
    if user is None or not user.active:
        return None
    row.last_seen = now
    db.flush()
    return user


def revoke(db: Session, token: str) -> None:
    row = db.get(AuthSession, _hash(token))
    if row is not None:
        db.delete(row)
        db.flush()


def revoke_all(db: Session, user_id: str) -> None:
    db.query(AuthSession).filter(AuthSession.user_id == user_id).delete()
    db.flush()
