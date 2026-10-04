"""Query API (Phase 4) with fail-closed audit logging (Phase 5).

Every query attempt is audited — served, rejected, or failed — and the audit
row is committed in the same request. A result is never returned unless its
audit row persisted.

SCAFFOLDING AUTH ONLY: user attributes arrive in the request body so the
pipeline can be exercised end to end. In production these MUST be derived
from the authenticated identity (PKI cert / IdP claims) by middleware —
never accepted from the client — and that swap is a review checkpoint
before any real data is connected.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from backend import config
from backend.auth.deps import Principal, optional_principal
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.audit import recorder
from backend.db.database import get_session
from backend.embedding.embedder import Embedder, get_embedder
from backend.models.marking import MarkingError
from backend.retrieval.filtered_search import RetrievalIntegrityError, filtered_search
from backend.retrieval.pdp import UserAttributes
from backend.retrieval.vector_store import VectorStore, get_vector_store

router = APIRouter(prefix="/query", tags=["query"])


class UserAttributesIn(BaseModel):
    user_id: str = Field(..., min_length=1)
    clearance: str = Field(..., examples=["S"])
    citizenship: str = Field(..., examples=["USA"])
    compartments: List[str] = Field(default_factory=list)
    need_to_know_groups: List[str] = Field(default_factory=list)


class QueryIn(BaseModel):
    query: str = Field(..., min_length=1)
    user: Optional[UserAttributesIn] = None
    top_k: int = Field(8, ge=1, le=50)


class HitOut(BaseModel):
    chunk_id: str
    parent_doc_id: str
    content: str
    score: float
    classification: str
    portion_marking: str
    dissem_controls: List[str]
    program: Optional[str]


class DecisionOut(BaseModel):
    chunk_id: str
    allow: str
    reason: str


class QueryOut(BaseModel):
    audit_id: str
    user_id: str
    hits: List[HitOut]
    filter_summary: dict
    decisions: List[DecisionOut]


@router.post("", response_model=QueryOut)
def run_query(
    payload: QueryIn,
    db: Session = Depends(get_session),
    embedder: Embedder = Depends(get_embedder),
    store: VectorStore = Depends(get_vector_store),
    principal: Optional[Principal] = Depends(optional_principal),
) -> QueryOut:
    if principal is not None:
        # Production path: attributes come only from the authenticated
        # identity. Any attributes in the body are ignored.
        u = principal.user
        payload.user = UserAttributesIn(
            user_id=u.username, clearance=u.clearance, citizenship=u.citizenship,
            compartments=list(u.compartments or []),
            need_to_know_groups=list(u.need_to_know_groups or []))
    elif config.auth_mode() != config.AUTH_MODE_SCAFFOLD:
        raise HTTPException(status_code=401, detail="sign-in required")
    elif payload.user is None:
        raise HTTPException(status_code=422, detail="user attributes required in scaffold mode")
    raw_attributes = payload.user.model_dump()

    try:
        user = UserAttributes(
            user_id=payload.user.user_id,
            clearance=payload.user.clearance,
            citizenship=payload.user.citizenship,
            compartments=payload.user.compartments,
            need_to_know_groups=payload.user.need_to_know_groups,
        )
    except MarkingError as exc:
        recorder.record_query_event(
            db,
            user_id=payload.user.user_id,
            user_attributes=raw_attributes,
            query_text=payload.query,
            top_k=payload.top_k,
            outcome=recorder.OUTCOME_REJECTED_ATTRIBUTES,
            result_count=0,
            detail=str(exc),
        )
        db.commit()
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        result = filtered_search(user, payload.query, embedder, store, top_k=payload.top_k)
    except RetrievalIntegrityError as exc:
        recorder.record_query_event(
            db,
            user_id=user.user_id,
            user_attributes=raw_attributes,
            query_text=payload.query,
            top_k=payload.top_k,
            clearance=user.clearance.value,
            citizenship=user.citizenship,
            outcome=recorder.OUTCOME_INTEGRITY_FAILURE,
            result_count=0,
            detail=str(exc),
        )
        db.commit()
        # Fail closed and loudly: nothing is returned if the store and PDP
        # ever disagree. This condition indicates a bug, not a user error.
        raise HTTPException(status_code=500, detail=str(exc))

    audit_id = recorder.record_query_event(
        db,
        user_id=user.user_id,
        user_attributes=raw_attributes,
        query_text=payload.query,
        top_k=payload.top_k,
        clearance=user.clearance.value,
        citizenship=user.citizenship,
        outcome=recorder.OUTCOME_OK,
        result_count=len(result.hits),
        filter_summary=result.filter_summary,
        returned_chunks=[
            {
                "chunk_id": h.chunk_id,
                "parent_doc_id": h.parent_doc_id,
                "classification": h.classification,
                "portion_marking": h.portion_marking,
                "dissem_controls": h.dissem_controls,
                "program": h.program,
            }
            for h in result.hits
        ],
        decisions=result.decisions,
    )
    # Commit before returning: the response is only served once audited.
    db.commit()

    return QueryOut(
        audit_id=audit_id,
        user_id=result.user_id,
        hits=[
            HitOut(
                chunk_id=h.chunk_id,
                parent_doc_id=h.parent_doc_id,
                content=h.content,
                score=h.score,
                classification=h.classification,
                portion_marking=h.portion_marking,
                dissem_controls=h.dissem_controls,
                program=h.program,
            )
            for h in result.hits
        ],
        filter_summary=result.filter_summary,
        decisions=[DecisionOut(**d) for d in result.decisions],
    )
