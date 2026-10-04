"""Audit recorder (Phase 5).

Writes one QueryAuditLog row per query attempt. The recorder adds and flushes
but does not commit — the caller commits the audit row in the same
transaction as the request, which is what makes auditing fail-closed: if the
audit row cannot be persisted, the response is never served.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from backend.models import schema

OUTCOME_OK = "ok"
OUTCOME_INTEGRITY_FAILURE = "integrity_failure"
OUTCOME_REJECTED_ATTRIBUTES = "rejected_attributes"


def record_query_event(
    db: Session,
    *,
    user_id: str,
    user_attributes: Dict[str, object],
    query_text: str,
    outcome: str,
    result_count: int,
    top_k: Optional[int] = None,
    clearance: Optional[str] = None,
    citizenship: Optional[str] = None,
    filter_summary: Optional[Dict[str, object]] = None,
    returned_chunks: Optional[List[Dict[str, object]]] = None,
    decisions: Optional[List[Dict[str, str]]] = None,
    detail: Optional[str] = None,
) -> str:
    """Add one audit row (uncommitted) and return its id."""
    entry = schema.QueryAuditLog(
        ts=datetime.now(timezone.utc),
        user_id=user_id,
        clearance=clearance,
        citizenship=citizenship,
        outcome=outcome,
        query_text=query_text,
        top_k=top_k,
        result_count=result_count,
        user_attributes=user_attributes,
        filter_summary=filter_summary,
        returned_chunks=returned_chunks,
        decisions=decisions,
        detail=detail,
    )
    db.add(entry)
    db.flush()
    return entry.id
