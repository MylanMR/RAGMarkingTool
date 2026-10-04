"""Release gate for AI-assisted products.

States: draft -> in_review -> (approved ->) released, with 'return' sending a
product back to draft. Rules that hold in every policy configuration:
- the author can never disposition, approve, or release their own product;
- every claim must carry a portion marking before submission (no defaults);
- a cited claim's marking must dominate the roll-up of its sources;
- the policy version is bound at submission, so a mid-review policy change
  cannot alter the rules a product is judged by;
- any content change after submission invalidates review (hash-checked).
The AO policy decides citation strictness and single vs two-person review.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from backend.governance import chain
from backend.models.governance import Product, ProductClaim
from backend.models.marking import MarkingError, PortionMarking
from backend.policy import store as policy_store
from backend.products import marking_roll

DISPOSITIONS = {
    "verified_offline": "Verified against source material outside the tool",
    "accept_judgment": "Accepted as the author's analytic judgment",
    "remove_required": "Must be removed or corrected (returns to author)",
}


class WorkflowError(ValueError):
    def __init__(self, msg: str, status: int = 422):
        super().__init__(msg)
        self.status = status


def _now():
    return datetime.now(timezone.utc)


def content_hash(product: Product) -> str:
    body = [{"text": c.text, "kind": c.kind, "marking": c.portion_marking,
             "cited": c.cited_sources} for c in product.claims]
    return hashlib.sha256(json.dumps([product.title, body], sort_keys=True)
                          .encode("utf-8")).hexdigest()


def source_marking(product: Product, nums: List[int]) -> Optional[PortionMarking]:
    by_num = {s.num: s for s in product.sources}
    ms = [PortionMarking.parse(by_num[n].portion_marking) for n in nums if n in by_num]
    return marking_roll.combine(ms) if ms else None


def current_marking(product: Product) -> Optional[PortionMarking]:
    """Marking used for read access: the roll-up of every source the product
    drew on plus every claim marking set so far."""
    ms = [PortionMarking.parse(s.portion_marking) for s in product.sources]
    ms += [PortionMarking.parse(c.portion_marking) for c in product.claims if c.portion_marking]
    return marking_roll.combine(ms) if ms else None


def required_dispositions(product: Product, mode: str) -> List[ProductClaim]:
    if mode == "advisory":
        return []
    need = []
    for c in product.claims:
        if c.invalid_refs or c.kind == "judgment" or (mode == "acknowledge" and c.kind == "uncited"):
            need.append(c)
    return need


def _event(db, actor, event_type, product, **payload):
    chain.record(db, actor=actor, event_type=event_type, subject_type="product",
                 subject_id=product.id, payload=payload)


def _require_state(product: Product, *states: str) -> None:
    if product.state not in states:
        raise WorkflowError("product is {}; action requires {}".format(
            product.state, " or ".join(states)), status=409)


def set_claim(db: Session, actor, product: Product, claim: ProductClaim, *,
              text: Optional[str] = None, kind: Optional[str] = None,
              portion_marking: Optional[str] = None) -> None:
    _require_state(product, "draft")
    if actor.id != product.author_id:
        raise WorkflowError("only the author can edit a draft", status=403)
    changes: Dict[str, object] = {}
    if text is not None:
        if not text.strip():
            raise WorkflowError("claim text cannot be empty")
        changes["text"] = {"from": claim.text, "to": text.strip()}
        claim.text = text.strip()
    if kind is not None:
        if claim.kind == "cited" or kind not in ("uncited", "judgment"):
            raise WorkflowError("only uncited claims can be tagged or untagged as analytic judgment")
        changes["kind"] = {"from": claim.kind, "to": kind}
        claim.kind = kind
    if portion_marking is not None:
        try:
            pm = PortionMarking.parse(portion_marking)
        except MarkingError as exc:
            raise WorkflowError(str(exc))
        if claim.derived_marking:
            floor = PortionMarking.parse(claim.derived_marking)
            if not marking_roll.dominates(pm, floor):
                raise WorkflowError(
                    "marking {} is below the roll-up of the cited sources {}".format(pm, floor))
        changes["portion_marking"] = {"from": claim.portion_marking, "to": str(pm)}
        claim.portion_marking = str(pm)
        claim.classification = pm.classification.value
        claim.dissem_controls = list(pm.dissem_controls)
    product.updated_at = _now()
    _event(db, actor.label, "product.claim_edited", product, claim_id=claim.id, changes=changes)


def delete_claim(db: Session, actor, product: Product, claim: ProductClaim) -> None:
    _require_state(product, "draft")
    if actor.id != product.author_id:
        raise WorkflowError("only the author can edit a draft", status=403)
    _event(db, actor.label, "product.claim_deleted", product, claim_id=claim.id,
           text=claim.text, kind=claim.kind)
    product.claims.remove(claim)
    product.updated_at = _now()


def submit(db: Session, actor, product: Product) -> None:
    _require_state(product, "draft")
    if actor.id != product.author_id:
        raise WorkflowError("only the author can submit", status=403)
    if not product.claims:
        raise WorkflowError("product has no claims")
    unmarked = [c.seq for c in product.claims if not c.portion_marking]
    if unmarked:
        raise WorkflowError("claims {} have no portion marking".format(unmarked))
    banner = marking_roll.combine(PortionMarking.parse(c.portion_marking) for c in product.claims)
    policy = policy_store.current(db)
    mode = policy.per_level("citation_enforcement", banner.classification.value)
    if mode == "block":
        uncited = [c.seq for c in product.claims if c.kind == "uncited"]
        if uncited:
            raise WorkflowError(
                "policy blocks uncited claims at {}: claims {} need a citation, removal, or an "
                "analytic-judgment tag".format(banner.classification.value, uncited))
    product.banner_classification = banner.classification.value
    product.banner_controls = list(banner.dissem_controls)
    product.policy_version = policy.version
    product.content_sha256 = content_hash(product)
    product.submitted_at = _now()
    product.return_note = None
    for c in product.claims:
        c.disposition = c.disposition_by = c.disposition_note = None
    product.state = "in_review"
    product.updated_at = _now()
    _event(db, actor.label, "product.submitted", product, banner=marking_roll.banner(banner),
           policy_version=policy.version, citation_mode=mode,
           review_rule=policy.per_level("review_rule", banner.classification.value),
           content_sha256=product.content_sha256)


def bound_policy(db: Session, product: Product):
    return policy_store.at_version(db, product.policy_version)


def _check_integrity(product: Product) -> None:
    if content_hash(product) != product.content_sha256:
        raise WorkflowError("product content changed after submission; review invalidated",
                            status=409)


def disposition(db: Session, actor, product: Product, claim: ProductClaim,
                value: str, note: Optional[str]) -> None:
    _require_state(product, "in_review")
    if actor.id == product.author_id:
        raise WorkflowError("authors cannot disposition their own claims", status=403)
    if value not in DISPOSITIONS:
        raise WorkflowError("disposition must be one of {}".format(list(DISPOSITIONS)))
    claim.disposition = value
    claim.disposition_by = actor.id
    claim.disposition_note = (note or "").strip() or None
    _event(db, actor.label, "product.claim_dispositioned", product, claim_id=claim.id,
           disposition=value, note=claim.disposition_note)


def approve(db: Session, actor, product: Product) -> None:
    _require_state(product, "in_review")
    if actor.id == product.author_id:
        raise WorkflowError("authors cannot approve their own product", status=403)
    _check_integrity(product)
    policy = bound_policy(db, product)
    level = product.banner_classification
    mode = policy.per_level("citation_enforcement", level)
    missing = [c.seq for c in required_dispositions(product, mode) if not c.disposition]
    if missing:
        raise WorkflowError("claims {} need a reviewer disposition".format(missing))
    removals = [c.seq for c in product.claims if c.disposition == "remove_required"]
    if removals:
        raise WorkflowError("claims {} are marked for removal; return the product to the author"
                            .format(removals))
    product.reviewer_id = actor.id
    product.reviewed_at = _now()
    rule = policy.per_level("review_rule", level)
    if rule == "single":
        product.releaser_id = actor.id
        product.released_at = _now()
        product.state = "released"
        _event(db, actor.label, "product.released", product, review_rule=rule,
               policy_version=product.policy_version, content_sha256=product.content_sha256)
    else:
        product.state = "approved"
        _event(db, actor.label, "product.approved", product, review_rule=rule,
               policy_version=product.policy_version)
    product.updated_at = _now()


def release(db: Session, actor, product: Product) -> None:
    _require_state(product, "approved")
    if actor.id in (product.author_id, product.reviewer_id):
        raise WorkflowError("two-person rule: releaser must differ from author and reviewer",
                            status=403)
    _check_integrity(product)
    product.releaser_id = actor.id
    product.released_at = _now()
    product.state = "released"
    product.updated_at = _now()
    _event(db, actor.label, "product.released", product, review_rule="two_person",
           policy_version=product.policy_version, content_sha256=product.content_sha256)


def return_to_author(db: Session, actor, product: Product, note: str) -> None:
    _require_state(product, "in_review", "approved")
    if actor.id == product.author_id:
        raise WorkflowError("authors cannot return their own product", status=403)
    if not (note or "").strip():
        raise WorkflowError("a return note is required")
    product.state = "draft"
    product.return_note = note.strip()
    product.reviewer_id = product.reviewed_at = None
    product.updated_at = _now()
    _event(db, actor.label, "product.returned", product, note=note.strip())
