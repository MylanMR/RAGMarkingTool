"""Roll a set of portion markings up to one marking (claim floor or banner).

Level: highest. Controls: union of the non-REL controls. Foreign release is
resolved conservatively and is FLAGGED FOR THE SECURITY REVIEW:
- any NOFORN portion makes the result NOFORN;
- if every classified portion carries REL TO, the result is REL TO the
  intersection of their country lists (empty intersection becomes NOFORN);
- if some classified portions carry REL TO and others carry no release
  marking, the result is NOFORN.
Unclassified portions do not affect foreign release.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Tuple

from backend.models.marking import ClassificationLevel, PortionMarking, highest_level

BANNER_NAMES = {"U": "UNCLASSIFIED", "C": "CONFIDENTIAL", "S": "SECRET",
                "TS": "TOP SECRET", "TS/SCI": "TOP SECRET//SCI"}


def _rel_countries(controls: List[str]) -> Optional[List[str]]:
    for c in controls:
        if c.startswith("REL TO "):
            return [x.strip() for x in c[7:].split(",")]
    return None


def combine(markings: Iterable[PortionMarking]) -> PortionMarking:
    ms = list(markings)
    if not ms:
        raise ValueError("cannot combine an empty marking set")
    level = highest_level([m.classification for m in ms])
    other: List[str] = []
    for m in ms:
        for c in m.dissem_controls:
            if not c.startswith("REL TO ") and c not in other:
                other.append(c)
    classified = [m for m in ms if m.classification is not ClassificationLevel.U]
    if classified and "NOFORN" not in other:
        rels = [_rel_countries(m.dissem_controls) for m in classified]
        if any(r is not None for r in rels):
            if all(r is not None for r in rels):
                common = [c for c in rels[0] if all(c in r for r in rels[1:])]
                if common:
                    other.append("REL TO " + ", ".join(common))
                else:
                    other.append("NOFORN")
            else:
                other.append("NOFORN")
    order = {"NOFORN": 0, "ORCON": 1, "PROPIN": 2, "RELIDO": 3, "NOCON": 4}
    other.sort(key=lambda c: order.get(c, 9))
    if level is ClassificationLevel.U:
        other = []
    return PortionMarking(classification=level, dissem_controls=other)


def dominates(a: PortionMarking, b: PortionMarking) -> bool:
    """True if marking a is at least as restrictive as b."""
    if not a.classification.dominates(b.classification):
        return False
    for c in b.dissem_controls:
        if c.startswith("REL TO "):
            if "NOFORN" in a.dissem_controls:
                continue
            ra = _rel_countries(a.dissem_controls)
            if ra is None or not set(ra) <= set(_rel_countries(b.dissem_controls)):
                return False
        elif c not in a.dissem_controls:
            return False
    return True


def banner(m: PortionMarking) -> str:
    name = BANNER_NAMES[m.classification.value]
    return name if not m.dissem_controls else name + "//" + "/".join(m.dissem_controls)
