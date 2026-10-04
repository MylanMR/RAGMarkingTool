"""Governance log API (auditor, AO): list events and verify the hash chain."""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.auth.deps import Principal, require_roles
from backend.db.database import get_session
from backend.governance import chain
from backend.models.governance import GovernanceEvent

router = APIRouter(prefix="/governance", tags=["governance"])


@router.get("/events")
def events(event_type: Optional[str] = None, subject_id: Optional[str] = None,
           limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0),
           p: Principal = Depends(require_roles("auditor", "ao")),
           db: Session = Depends(get_session)) -> list:
    q = db.query(GovernanceEvent)
    if event_type:
        q = q.filter(GovernanceEvent.event_type.like(event_type.replace("*", "%")))
    if subject_id:
        q = q.filter(GovernanceEvent.subject_id == subject_id)
    rows = q.order_by(GovernanceEvent.seq.desc()).offset(offset).limit(limit).all()
    return [{"seq": e.seq, "ts": e.ts.isoformat(), "actor": e.actor,
             "event_type": e.event_type, "subject_type": e.subject_type,
             "subject_id": e.subject_id, "payload": e.payload, "hash": e.hash} for e in rows]


@router.get("/verify")
def verify(p: Principal = Depends(require_roles("auditor", "ao")),
           db: Session = Depends(get_session)) -> dict:
    ok, bad, n = chain.verify(db)
    return {"intact": ok, "first_bad_seq": bad, "events_checked": n}
