"""AI-assisted product API: draft (retrieve, ceiling-filter, generate, parse
claims), edit, submit, disposition, approve, release, return, export.

Read access to any product is a PDP decision on the product's roll-up
marking, so a product is never shown to someone who could not see its
sources."""

from __future__ import annotations

import hashlib
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.audit import recorder
from backend.auth.deps import Principal, require_principal, require_roles
from backend.db.database import get_session
from backend.embedding.embedder import Embedder, get_embedder
from backend.governance import chain
from backend.llm import adapters, egress, prompt
from backend.models import schema
from backend.models.governance import (ModelEndpoint, Product, ProductClaim, ProductSource,
                                       User)
from backend.models.marking import PortionMarking
from backend.policy import store as policy_store
from backend.products import claims as claim_parser
from backend.products import export, marking_roll, workflow
from backend.retrieval import pdp
from backend.retrieval.filtered_search import RetrievalIntegrityError, filtered_search
from backend.retrieval.vector_store import VectorStore, get_vector_store

router = APIRouter(prefix="/products", tags=["products"])


class DraftIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    question: str = Field(..., min_length=1, max_length=4000)
    model_endpoint_id: str
    top_k: int = Field(8, ge=1, le=30)


class ClaimPatch(BaseModel):
    text: Optional[str] = None
    kind: Optional[str] = None
    portion_marking: Optional[str] = None


class DispositionIn(BaseModel):
    disposition: str
    note: Optional[str] = None


class NoteIn(BaseModel):
    note: str = ""


def _wf(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except workflow.WorkflowError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))


def _load(db: Session, p: Principal, product_id: str) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")
    m = workflow.current_marking(product)
    if m is not None:
        d = pdp.decide(p.attributes(), m.classification.value, list(m.dissem_controls), None)
        programs = {s.program for s in product.sources if s.program}
        if not d.allow or not programs <= set(p.user.compartments or []):
            # Same response as a missing product: no existence oracle.
            raise HTTPException(status_code=404, detail="product not found")
    return product


def _claim(product: Product, claim_id: str) -> ProductClaim:
    c = next((c for c in product.claims if c.id == claim_id), None)
    if c is None:
        raise HTTPException(status_code=404, detail="claim not found")
    return c


def _names(db: Session, ids) -> dict:
    ids = [i for i in ids if i]
    return {u.id: u.display_name for u in db.query(User).filter(User.id.in_(ids)).all()} if ids else {}


def product_out(db: Session, product: Product, p: Principal, detail: bool = True) -> dict:
    policy_v = workflow.bound_policy(db, product) if product.policy_version else \
        policy_store.current(db)
    m = workflow.current_marking(product)
    level = product.banner_classification or (m.classification.value if m else "U")
    mode = policy_v.per_level("citation_enforcement", level)
    rule = policy_v.per_level("review_rule", level)
    names = _names(db, [product.author_id, product.reviewer_id, product.releaser_id])
    out = {
        "id": product.id, "title": product.title, "state": product.state,
        "author": names.get(product.author_id), "author_id": product.author_id,
        "is_author": product.author_id == p.id,
        "banner": marking_roll.banner(m) if m else None,
        "policy_version": product.policy_version, "citation_mode": mode, "review_rule": rule,
        "created_at": product.created_at.isoformat(),
        "updated_at": product.updated_at.isoformat(),
        "return_note": product.return_note,
        "counts": {"claims": len(product.claims),
                   "uncited": sum(1 for c in product.claims if c.kind == "uncited"),
                   "judgment": sum(1 for c in product.claims if c.kind == "judgment"),
                   "invalid_refs": sum(1 for c in product.claims if c.invalid_refs)},
    }
    if not detail:
        return out
    required = {c.id for c in workflow.required_dispositions(product, mode)}
    chunk_ids = [s.chunk_id for s in product.sources]
    chunks = {c.chunk_id: c for c in db.query(schema.Chunk)
              .filter(schema.Chunk.chunk_id.in_(chunk_ids)).all()} if chunk_ids else {}
    out.update({
        "question": product.question,
        "reviewer": names.get(product.reviewer_id), "releaser": names.get(product.releaser_id),
        "disclosure": {"model_name": product.model_name, "adapter": product.adapter,
                       "model_requested": product.model_id_requested,
                       "model_reported": product.model_id_reported,
                       "ceiling": product.model_ceiling,
                       "withheld_count": len(product.withheld_chunk_ids or []),
                       "prompt_sha256": product.prompt_sha256,
                       "raw_output_sha256": product.raw_output_sha256},
        "claims": [{"id": c.id, "seq": c.seq, "text": c.text, "kind": c.kind,
                    "cited_sources": c.cited_sources, "invalid_refs": c.invalid_refs,
                    "derived_marking": c.derived_marking, "portion_marking": c.portion_marking,
                    "disposition": c.disposition, "disposition_note": c.disposition_note,
                    "needs_disposition": c.id in required} for c in product.claims],
        "sources": [{"num": s.num, "chunk_id": s.chunk_id, "doc_title": s.doc_title,
                     "parent_doc_id": s.parent_doc_id, "portion_marking": s.portion_marking,
                     "source_system": s.source_system,
                     "content": chunks[s.chunk_id].content if s.chunk_id in chunks else None}
                    for s in product.sources],
        "dispositions": workflow.DISPOSITIONS,
    })
    return out


@router.post("", status_code=201)
def draft(payload: DraftIn, p: Principal = Depends(require_roles("author")),
          db: Session = Depends(get_session), embedder: Embedder = Depends(get_embedder),
          store: VectorStore = Depends(get_vector_store)) -> dict:
    ep = db.get(ModelEndpoint, payload.model_endpoint_id)
    if ep is None:
        raise HTTPException(status_code=404, detail="model endpoint not found")
    policy = policy_store.current(db)
    try:
        egress.check(ep, policy)
    except egress.EgressDenied as exc:
        chain.record(db, actor=p.label, event_type="model.call_refused", subject_type="model",
                     subject_id=ep.id, payload={"reason": str(exc)})
        db.commit()
        raise HTTPException(status_code=403, detail=str(exc))

    user = p.attributes()
    try:
        result = filtered_search(user, payload.question, embedder, store, top_k=payload.top_k)
    except RetrievalIntegrityError as exc:
        recorder.record_query_event(db, user_id=user.user_id, user_attributes=vars(user) | {
            "clearance": user.clearance.value}, query_text=payload.question,
            top_k=payload.top_k, outcome=recorder.OUTCOME_INTEGRITY_FAILURE, result_count=0,
            detail=str(exc))
        db.commit()
        raise HTTPException(status_code=500, detail=str(exc))
    audit_id = recorder.record_query_event(
        db, user_id=user.user_id,
        user_attributes={"user_id": user.user_id, "clearance": user.clearance.value,
                         "citizenship": user.citizenship, "compartments": user.compartments,
                         "need_to_know_groups": user.need_to_know_groups},
        query_text=payload.question, top_k=payload.top_k, clearance=user.clearance.value,
        citizenship=user.citizenship, outcome=recorder.OUTCOME_OK,
        result_count=len(result.hits), filter_summary=result.filter_summary,
        returned_chunks=[{"chunk_id": h.chunk_id, "portion_marking": h.portion_marking}
                         for h in result.hits], decisions=result.decisions,
        detail="product draft retrieval")

    ceiling = egress.effective_ceiling(ep, policy)
    allowed, withheld = egress.split_by_ceiling(result.hits, ceiling)
    if not allowed:
        db.commit()
        raise HTTPException(status_code=422, detail=(
            "no retrievable sources at or below the model's ceiling ({}); {} withheld"
            .format(ceiling, len(withheld))))
    system, user_prompt, prompt_hash = prompt.build(payload.question, allowed)
    try:
        completion = adapters.generate(ep, system, user_prompt)
    except adapters.AdapterError as exc:
        chain.record(db, actor=p.label, event_type="model.call_failed", subject_type="model",
                     subject_id=ep.id, payload={"reason": str(exc), "prompt_sha256": prompt_hash})
        db.commit()
        raise HTTPException(status_code=502, detail=str(exc))

    product = Product(
        title=payload.title.strip(), question=payload.question.strip(), author_id=p.id,
        state="draft", model_endpoint_id=ep.id, model_name=ep.name, adapter=ep.adapter,
        model_id_requested=ep.model_id, model_id_reported=completion.model_reported,
        model_ceiling=ceiling, prompt_sha256=prompt_hash,
        raw_output_sha256=hashlib.sha256(completion.text.encode("utf-8")).hexdigest(),
        withheld_chunk_ids=[h.chunk_id for h in withheld], query_audit_id=audit_id)
    titles = {d.id: d.title for d in db.query(schema.Document)
              .filter(schema.Document.id.in_([h.parent_doc_id for h in allowed])).all()}
    for i, h in enumerate(allowed, start=1):
        product.sources.append(ProductSource(
            num=i, chunk_id=h.chunk_id, parent_doc_id=h.parent_doc_id,
            doc_title=titles.get(h.parent_doc_id, "untitled"), source_system="retrieval",
            portion_marking=h.portion_marking, classification=h.classification,
            dissem_controls=list(h.dissem_controls), program=h.program))
    for seq, pc in enumerate(claim_parser.parse(completion.text, len(allowed)), start=1):
        floor = workflow.source_marking(product, pc.cited)
        product.claims.append(ProductClaim(
            seq=seq, text=pc.text, kind=pc.kind, cited_sources=pc.cited, invalid_refs=pc.invalid,
            derived_marking=str(floor) if floor else None,
            # Cited claims start at their source roll-up; uncited claims stay
            # unmarked until the author marks them (no silent default).
            portion_marking=str(floor) if floor else None,
            classification=floor.classification.value if floor else None,
            dissem_controls=list(floor.dissem_controls) if floor else None))
    if not product.claims:
        db.commit()
        raise HTTPException(status_code=502, detail="model returned no usable text")
    db.add(product)
    db.flush()
    chain.record(db, actor=p.label, event_type="product.drafted", subject_type="product",
                 subject_id=product.id, payload={
                     "model_endpoint_id": ep.id, "model_name": ep.name, "adapter": ep.adapter,
                     "model_requested": ep.model_id, "model_reported": completion.model_reported,
                     "ceiling": ceiling, "prompt_sha256": prompt_hash,
                     "raw_output_sha256": product.raw_output_sha256,
                     "source_chunk_ids": [h.chunk_id for h in allowed],
                     "withheld_chunk_ids": product.withheld_chunk_ids,
                     "query_audit_id": audit_id})
    db.commit()
    return product_out(db, product, p)


@router.get("")
def list_products(view: str = "mine", p: Principal = Depends(require_principal),
                  db: Session = Depends(get_session)) -> list:
    q = db.query(Product)
    if view == "mine":
        q = q.filter(Product.author_id == p.id)
    elif view == "review":
        if not p.roles.intersection({"reviewer"}):
            raise HTTPException(status_code=403, detail="requires role: reviewer")
        q = q.filter(Product.state == "in_review", Product.author_id != p.id)
    elif view == "release":
        if not p.roles.intersection({"releaser"}):
            raise HTTPException(status_code=403, detail="requires role: releaser")
        q = q.filter(Product.state == "approved", Product.author_id != p.id,
                     Product.reviewer_id != p.id)
    elif view == "released":
        q = q.filter(Product.state == "released")
    else:
        raise HTTPException(status_code=422, detail="view must be mine, review, release, released")
    out = []
    for prod in q.order_by(Product.updated_at.desc()).limit(200).all():
        try:
            _load(db, p, prod.id)
        except HTTPException:
            continue
        out.append(product_out(db, prod, p, detail=False))
    return out


@router.get("/{product_id}")
def get_product(product_id: str, p: Principal = Depends(require_principal),
                db: Session = Depends(get_session)) -> dict:
    return product_out(db, _load(db, p, product_id), p)


@router.patch("/{product_id}/claims/{claim_id}")
def edit_claim(product_id: str, claim_id: str, payload: ClaimPatch,
               p: Principal = Depends(require_roles("author")),
               db: Session = Depends(get_session)) -> dict:
    product = _load(db, p, product_id)
    _wf(workflow.set_claim, db, p, product, _claim(product, claim_id), **payload.model_dump())
    db.commit()
    return product_out(db, product, p)


@router.delete("/{product_id}/claims/{claim_id}")
def remove_claim(product_id: str, claim_id: str, p: Principal = Depends(require_roles("author")),
                 db: Session = Depends(get_session)) -> dict:
    product = _load(db, p, product_id)
    _wf(workflow.delete_claim, db, p, product, _claim(product, claim_id))
    db.commit()
    return product_out(db, product, p)


@router.post("/{product_id}/submit")
def submit(product_id: str, p: Principal = Depends(require_roles("author")),
           db: Session = Depends(get_session)) -> dict:
    product = _load(db, p, product_id)
    _wf(workflow.submit, db, p, product)
    db.commit()
    return product_out(db, product, p)


@router.post("/{product_id}/claims/{claim_id}/disposition")
def set_disposition(product_id: str, claim_id: str, payload: DispositionIn,
                    p: Principal = Depends(require_roles("reviewer")),
                    db: Session = Depends(get_session)) -> dict:
    product = _load(db, p, product_id)
    _wf(workflow.disposition, db, p, product, _claim(product, claim_id),
        payload.disposition, payload.note)
    db.commit()
    return product_out(db, product, p)


@router.post("/{product_id}/approve")
def approve(product_id: str, p: Principal = Depends(require_roles("reviewer")),
            db: Session = Depends(get_session)) -> dict:
    product = _load(db, p, product_id)
    _wf(workflow.approve, db, p, product)
    db.commit()
    return product_out(db, product, p)


@router.post("/{product_id}/release")
def release(product_id: str, p: Principal = Depends(require_roles("releaser")),
            db: Session = Depends(get_session)) -> dict:
    product = _load(db, p, product_id)
    _wf(workflow.release, db, p, product)
    db.commit()
    return product_out(db, product, p)


@router.post("/{product_id}/return")
def return_product(product_id: str, payload: NoteIn,
                   p: Principal = Depends(require_roles("reviewer", "releaser")),
                   db: Session = Depends(get_session)) -> dict:
    product = _load(db, p, product_id)
    _wf(workflow.return_to_author, db, p, product, payload.note)
    db.commit()
    return product_out(db, product, p)


@router.get("/{product_id}/export", response_class=PlainTextResponse)
def export_product(product_id: str, p: Principal = Depends(require_principal),
                   db: Session = Depends(get_session)) -> PlainTextResponse:
    product = _load(db, p, product_id)
    if product.state != "released" and p.id != product.author_id and \
            not p.roles.intersection({"reviewer", "releaser"}):
        raise HTTPException(status_code=403, detail="unreleased products export only to the "
                                                    "author, reviewers, and releasers")
    chain.record(db, actor=p.label, event_type="product.exported", subject_type="product",
                 subject_id=product.id, payload={"state": product.state})
    db.commit()
    names = _names(db, [product.author_id, product.reviewer_id, product.releaser_id])
    return PlainTextResponse(export.render(product, names), media_type="text/markdown")
