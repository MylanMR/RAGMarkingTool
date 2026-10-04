"""Hash-chained governance log.

Each event's hash covers the previous event's hash plus the canonical JSON of
its own content, so editing or deleting any row breaks verification from that
row forward. Writers serialize on a Postgres advisory lock so two concurrent
transactions can never chain off the same predecessor. Like the query audit
recorder, ``record`` flushes but does not commit: the caller commits the
event in the same transaction as the change it describes (fail closed).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.models.governance import GovernanceEvent

GENESIS = "0" * 64
_LOCK_KEY = 727274


def _canonical(ts: str, actor: str, event_type: str, subject_type: str,
               subject_id: str, payload: Dict) -> str:
    return json.dumps(
        {"ts": ts, "actor": actor, "event_type": event_type,
         "subject_type": subject_type, "subject_id": subject_id, "payload": payload},
        sort_keys=True, separators=(",", ":"), default=str,
    )


def _digest(prev_hash: str, body: str) -> str:
    return hashlib.sha256((prev_hash + body).encode("utf-8")).hexdigest()


def record(db: Session, *, actor: str, event_type: str, subject_type: str,
           subject_id: str, payload: Optional[Dict] = None) -> GovernanceEvent:
    payload = payload or {}
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY})
    last = db.query(GovernanceEvent).order_by(GovernanceEvent.seq.desc()).first()
    prev = last.hash if last else GENESIS
    ts = datetime.now(timezone.utc)
    ts_s = ts.isoformat()
    # The exact timestamp string hashed is stored in the payload so
    # verification does not depend on how the database round-trips timezones.
    stored = dict(payload, _ts=ts_s)
    body = _canonical(ts_s, actor, event_type, subject_type, str(subject_id), stored)
    ev = GovernanceEvent(ts=ts, actor=actor, event_type=event_type,
                         subject_type=subject_type, subject_id=str(subject_id),
                         payload=stored, prev_hash=prev, hash=_digest(prev, body))
    db.add(ev)
    db.flush()
    return ev


def verify(db: Session) -> Tuple[bool, Optional[int], int]:
    """Return (intact, first_bad_seq, events_checked)."""
    prev = GENESIS
    n = 0
    for ev in db.query(GovernanceEvent).order_by(GovernanceEvent.seq.asc()).yield_per(500):
        n += 1
        ts_s = (ev.payload or {}).get("_ts", "")
        body = _canonical(ts_s, ev.actor, ev.event_type, ev.subject_type,
                          ev.subject_id, ev.payload)
        if ev.prev_hash != prev or _digest(prev, body) != ev.hash:
            return False, ev.seq, n
        prev = ev.hash
    return True, None, n
