"""AO risk-policy API. Reading the catalog is open to any signed-in user (the
UI shows people which rules apply); changing it requires the AO role."""

from __future__ import annotations

from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth.deps import Principal, require_principal, require_roles
from backend.db.database import get_session
from backend.policy import catalog, store

router = APIRouter(prefix="/policy", tags=["policy"])


class PolicyIn(BaseModel):
    settings: Dict[str, object]
    justification: Optional[str] = None


def _out(pol) -> dict:
    return {"version": pol.version, "settings": pol.settings, "catalog": catalog.catalog_json(),
            "min_justification": store.MIN_JUSTIFICATION}


@router.get("")
def get_policy(p: Principal = Depends(require_principal), db: Session = Depends(get_session)) -> dict:
    pol = store.current(db)
    db.commit()
    return _out(pol)


@router.put("")
def put_policy(payload: PolicyIn, p: Principal = Depends(require_roles("ao")),
               db: Session = Depends(get_session)) -> dict:
    try:
        pol = store.update(db, actor=p.label, settings=payload.settings,
                           justification=payload.justification)
    except catalog.PolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    db.commit()
    return _out(pol)


@router.get("/history")
def history(p: Principal = Depends(require_roles("ao", "auditor", "admin")),
            db: Session = Depends(get_session)) -> list:
    return [{"version": r.version, "changed_by": r.changed_by,
             "changed_at": r.changed_at.isoformat(), "relaxed": r.relaxed,
             "justification": r.justification, "settings": r.settings}
            for r in store.history(db)]
