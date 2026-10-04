"""Model endpoint registry. Admins add and enable endpoints; an AO approves
non-local endpoints. Changing an endpoint's URL, model, adapter, or ceiling
clears its approval and disables it."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.auth.deps import Principal, require_principal, require_roles
from backend.db.database import get_session
from backend.governance import chain
from backend.llm import adapters, egress
from backend.models.governance import ModelEndpoint
from backend.policy import catalog, store as policy_store

router = APIRouter(prefix="/models", tags=["models"])
_RESET_FIELDS = {"adapter", "base_url", "model_id", "max_classification"}


class EndpointIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    adapter: str
    base_url: str
    model_id: str = Field(..., min_length=1)
    max_classification: str
    credential_ref: Optional[str] = None
    extra: Dict[str, object] = Field(default_factory=dict)


class EndpointPatch(BaseModel):
    name: Optional[str] = None
    adapter: Optional[str] = None
    base_url: Optional[str] = None
    model_id: Optional[str] = None
    max_classification: Optional[str] = None
    credential_ref: Optional[str] = None
    extra: Optional[Dict[str, object]] = None
    enabled: Optional[bool] = None


def _out(ep: ModelEndpoint, admin: bool) -> dict:
    local = None
    host = urlparse(ep.base_url).hostname
    if host:
        local = egress._host_is_local(host)[0]
    out = {"id": ep.id, "name": ep.name, "adapter": ep.adapter, "model_id": ep.model_id,
           "max_classification": ep.max_classification, "enabled": ep.enabled,
           "local": local or ep.adapter == "dev_extractive",
           "approved_by": ep.approved_by,
           "approved_at": ep.approved_at.isoformat() if ep.approved_at else None}
    if admin:
        out.update({"base_url": ep.base_url, "credential_ref": ep.credential_ref,
                    "extra": ep.extra, "created_by": ep.created_by})
    return out


def _validate(db: Session, adapter: str, ceiling: str, cred: Optional[str]) -> None:
    if adapter not in adapters.available_adapters():
        raise HTTPException(status_code=422, detail="unknown or unavailable adapter")
    if ceiling not in catalog.LEVELS:
        raise HTTPException(status_code=422, detail="max_classification must be one of {}"
                            .format(catalog.LEVELS))
    sh = policy_store.current(db).system_high
    if catalog.level_rank(ceiling) > catalog.level_rank(sh):
        raise HTTPException(status_code=422, detail="ceiling {} exceeds system high {}"
                            .format(ceiling, sh))
    if cred and not (cred.startswith("env:") or cred.startswith("file:")):
        raise HTTPException(status_code=422, detail=(
            "credential_ref must reference a secret (env:NAME or file:/path); "
            "secrets are never stored in the database"))


@router.get("/adapters")
def list_adapters(p: Principal = Depends(require_principal)) -> list:
    return [{"value": k, "label": v["label"]} for k, v in adapters.available_adapters().items()]


@router.get("")
def list_endpoints(p: Principal = Depends(require_principal),
                   db: Session = Depends(get_session)) -> list:
    privileged = bool(p.roles.intersection({"admin", "ao", "auditor"}))
    q = db.query(ModelEndpoint)
    if not privileged:
        q = q.filter(ModelEndpoint.enabled.is_(True))
    return [_out(e, privileged) for e in q.order_by(ModelEndpoint.name).all()]


@router.post("", status_code=201)
def add_endpoint(payload: EndpointIn, p: Principal = Depends(require_roles("admin")),
                 db: Session = Depends(get_session)) -> dict:
    _validate(db, payload.adapter, payload.max_classification, payload.credential_ref)
    if db.query(ModelEndpoint).filter(ModelEndpoint.name == payload.name).first():
        raise HTTPException(status_code=409, detail="an endpoint with that name exists")
    ep = ModelEndpoint(**payload.model_dump(), enabled=False, created_by=p.user.username)
    db.add(ep)
    db.flush()
    chain.record(db, actor=p.label, event_type="model.created", subject_type="model",
                 subject_id=ep.id, payload=_out(ep, True))
    db.commit()
    return _out(ep, True)


@router.patch("/{endpoint_id}")
def edit_endpoint(endpoint_id: str, payload: EndpointPatch,
                  p: Principal = Depends(require_roles("admin")),
                  db: Session = Depends(get_session)) -> dict:
    ep = db.get(ModelEndpoint, endpoint_id)
    if ep is None:
        raise HTTPException(status_code=404, detail="endpoint not found")
    changes = payload.model_dump(exclude_none=True)
    _validate(db, changes.get("adapter", ep.adapter),
              changes.get("max_classification", ep.max_classification),
              changes.get("credential_ref", ep.credential_ref))
    reset = bool(_RESET_FIELDS.intersection(k for k, v in changes.items() if getattr(ep, k) != v))
    for k, v in changes.items():
        setattr(ep, k, v)
    if reset:
        ep.approved_by = ep.approved_at = None
        if "enabled" not in changes:
            ep.enabled = False
    chain.record(db, actor=p.label, event_type="model.updated", subject_type="model",
                 subject_id=ep.id, payload={"changes": changes, "approval_cleared": reset})
    db.commit()
    return _out(ep, True)


@router.post("/{endpoint_id}/approve")
def approve_endpoint(endpoint_id: str, p: Principal = Depends(require_roles("ao")),
                     db: Session = Depends(get_session)) -> dict:
    ep = db.get(ModelEndpoint, endpoint_id)
    if ep is None:
        raise HTTPException(status_code=404, detail="endpoint not found")
    if ep.created_by == p.user.username:
        raise HTTPException(status_code=403, detail="an AO cannot approve an endpoint they created")
    ep.approved_by = p.user.username
    ep.approved_at = datetime.now(timezone.utc)
    chain.record(db, actor=p.label, event_type="model.approved", subject_type="model",
                 subject_id=ep.id, payload={"base_url": ep.base_url, "model_id": ep.model_id,
                                            "ceiling": ep.max_classification})
    db.commit()
    return _out(ep, True)


@router.post("/{endpoint_id}/revoke")
def revoke_endpoint(endpoint_id: str, p: Principal = Depends(require_roles("ao")),
                    db: Session = Depends(get_session)) -> dict:
    ep = db.get(ModelEndpoint, endpoint_id)
    if ep is None:
        raise HTTPException(status_code=404, detail="endpoint not found")
    ep.approved_by = ep.approved_at = None
    ep.enabled = False
    chain.record(db, actor=p.label, event_type="model.approval_revoked", subject_type="model",
                 subject_id=ep.id, payload={})
    db.commit()
    return _out(ep, True)
