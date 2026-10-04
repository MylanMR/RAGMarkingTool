"""Versioned policy storage. Version 1 (catalog defaults) is created on first
read and recorded in the governance chain."""

from __future__ import annotations

from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from backend.governance import chain
from backend.models.governance import PolicyVersion
from backend.policy import catalog

MIN_JUSTIFICATION = 20


class Policy:
    def __init__(self, row: PolicyVersion):
        self.version = row.version
        self.settings: Dict[str, object] = row.settings

    def per_level(self, key: str, level: str) -> str:
        return self.settings[key][level]

    def get(self, key: str) -> str:
        return self.settings[key]

    @property
    def system_high(self) -> str:
        return self.settings["system_high"]


def current(db: Session) -> Policy:
    row = db.query(PolicyVersion).order_by(PolicyVersion.version.desc()).first()
    if row is None:
        row = PolicyVersion(version=1, settings=catalog.defaults(), relaxed=[],
                            justification="Initial secure defaults", changed_by="system")
        db.add(row)
        chain.record(db, actor="system", event_type="policy.initialized",
                     subject_type="policy", subject_id="1",
                     payload={"settings": row.settings})
        db.flush()
    return Policy(row)


def at_version(db: Session, version: int) -> Policy:
    row = db.get(PolicyVersion, version)
    if row is None:
        raise catalog.PolicyError("policy version {} not found".format(version))
    return Policy(row)


def update(db: Session, *, actor: str, settings: Dict[str, object],
           justification: Optional[str]) -> Policy:
    new = catalog.validate(settings)
    cur = current(db)
    relaxed = catalog.relaxations(cur.settings, new)
    just = (justification or "").strip()
    if relaxed and len(just) < MIN_JUSTIFICATION:
        raise catalog.PolicyError(
            "relaxing {} requires a written justification of at least {} characters"
            .format(", ".join(relaxed), MIN_JUSTIFICATION))
    if new == cur.settings:
        raise catalog.PolicyError("no changes to save")
    row = PolicyVersion(version=cur.version + 1, settings=new, relaxed=relaxed,
                        justification=just or None, changed_by=actor)
    db.add(row)
    chain.record(db, actor=actor, event_type="policy.changed", subject_type="policy",
                 subject_id=str(row.version),
                 payload={"from_version": cur.version, "settings": new,
                          "relaxed": relaxed, "justification": just or None})
    db.flush()
    return Policy(row)


def history(db: Session) -> List[PolicyVersion]:
    return db.query(PolicyVersion).order_by(PolicyVersion.version.desc()).all()
