"""Audit read API (Phase 5): the log is queryable, not append-only text.

SECURITY NOTE: audit rows contain query text, user attributes, and the
markings of returned chunks — the log itself is sensitive. Production must
restrict these endpoints to an auditor role; that is part of the access
control walkthrough required before connecting a production IdP.
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from backend.audit.recorder import (
    OUTCOME_INTEGRITY_FAILURE,
    OUTCOME_OK,
    OUTCOME_REJECTED_ATTRIBUTES,
)
from backend.db.database import get_session
from backend.models import schema

router = APIRouter(prefix="/audit", tags=["audit"])

_VALID_OUTCOMES = {OUTCOME_OK, OUTCOME_INTEGRITY_FAILURE, OUTCOME_REJECTED_ATTRIBUTES}


class AuditEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    ts: datetime
    user_id: str
    clearance: Optional[str]
    citizenship: Optional[str]
    outcome: str
    query_text: str
    top_k: Optional[int]
    result_count: int
    user_attributes: dict
    filter_summary: Optional[dict]
    returned_chunks: Optional[list]
    decisions: Optional[list]
    detail: Optional[str]


class AuditPageOut(BaseModel):
    total: int
    entries: List[AuditEntryOut]


@router.get("/queries", response_model=AuditPageOut)
def list_query_events(
    user_id: Optional[str] = None,
    outcome: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_session),
) -> AuditPageOut:
    if outcome is not None and outcome not in _VALID_OUTCOMES:
        raise HTTPException(
            status_code=422,
            detail="unknown outcome {!r}; expected one of {}".format(
                outcome, sorted(_VALID_OUTCOMES)
            ),
        )
    q = db.query(schema.QueryAuditLog)
    if user_id is not None:
        q = q.filter(schema.QueryAuditLog.user_id == user_id)
    if outcome is not None:
        q = q.filter(schema.QueryAuditLog.outcome == outcome)
    if since is not None:
        q = q.filter(schema.QueryAuditLog.ts >= since)
    if until is not None:
        q = q.filter(schema.QueryAuditLog.ts <= until)
    total = q.count()
    rows = (
        q.order_by(schema.QueryAuditLog.ts.desc(), schema.QueryAuditLog.id)
        .offset(offset)
        .limit(limit)
        .all()
    )
    return AuditPageOut(
        total=total, entries=[AuditEntryOut.model_validate(r) for r in rows]
    )


@router.get("/queries/{audit_id}", response_model=AuditEntryOut)
def get_query_event(audit_id: str, db: Session = Depends(get_session)) -> AuditEntryOut:
    row = db.query(schema.QueryAuditLog).filter(schema.QueryAuditLog.id == audit_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="no audit entry {}".format(audit_id))
    return AuditEntryOut.model_validate(row)
