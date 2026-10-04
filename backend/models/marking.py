"""Classification marking domain model.

Single source of truth for classification levels, dissemination controls,
and portion-marking parsing. Nothing in this module ever supplies a default
classification: a missing or malformed marking is always a MarkingError.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field
from typing import List, Optional


class MarkingError(ValueError):
    """Raised when a marking is missing, malformed, or internally inconsistent."""


@enum.unique
class ClassificationLevel(enum.Enum):
    U = "U"
    C = "C"
    S = "S"
    TS = "TS"
    TS_SCI = "TS/SCI"

    @property
    def rank(self) -> int:
        return _RANK[self]

    def dominates(self, other: "ClassificationLevel") -> bool:
        """True if this level is at or above ``other``."""
        return self.rank >= other.rank

    @classmethod
    def parse(cls, raw: object) -> "ClassificationLevel":
        if isinstance(raw, cls):
            return raw
        if not isinstance(raw, str) or not raw.strip():
            raise MarkingError("classification level is missing")
        token = raw.strip().upper()
        try:
            return cls(token)
        except ValueError:
            raise MarkingError(
                "unknown classification level {!r}; expected one of U, C, S, TS, "
                "TS/SCI".format(raw)
            ) from None


_RANK = {
    ClassificationLevel.U: 0,
    ClassificationLevel.C: 1,
    ClassificationLevel.S: 2,
    ClassificationLevel.TS: 3,
    ClassificationLevel.TS_SCI: 4,
}

# Canonical dissemination-control names, keyed by every accepted spelling.
_CONTROL_ALIASES = {
    "NF": "NOFORN",
    "NOFORN": "NOFORN",
    "OC": "ORCON",
    "ORCON": "ORCON",
    "PR": "PROPIN",
    "PROPIN": "PROPIN",
    "RELIDO": "RELIDO",
    "NOCON": "NOCON",
}

_REL_TO_RE = re.compile(r"^REL(?:\s+TO)?\s+(?P<countries>[A-Z]{3}(?:\s*,\s*[A-Z]{3})*)$")

_PORTION_RE = re.compile(r"^\((?P<body>[^()]+)\)$")


def normalize_dissem_control(raw: str) -> str:
    """Canonicalize one dissemination-control token, or raise MarkingError."""
    if not isinstance(raw, str) or not raw.strip():
        raise MarkingError("dissemination control token is empty")
    token = re.sub(r"\s+", " ", raw.strip().upper())
    if token in _CONTROL_ALIASES:
        return _CONTROL_ALIASES[token]
    rel = _REL_TO_RE.match(token)
    if rel:
        countries = [c.strip() for c in rel.group("countries").split(",")]
        return "REL TO " + ", ".join(countries)
    raise MarkingError("unknown dissemination control {!r}".format(raw))


def validate_dissem_controls(controls: List[str]) -> List[str]:
    """Canonicalize a control list and reject contradictory combinations."""
    normalized = [normalize_dissem_control(c) for c in controls]
    seen: List[str] = []
    for c in normalized:
        if c not in seen:
            seen.append(c)
    has_rel = any(c.startswith("REL TO ") for c in seen)
    if has_rel and "NOFORN" in seen:
        raise MarkingError("NOFORN and REL TO are mutually exclusive")
    if sum(1 for c in seen if c.startswith("REL TO ")) > 1:
        raise MarkingError("multiple REL TO statements in one marking")
    return seen


@dataclass(frozen=True)
class PortionMarking:
    """A parsed portion marking such as ``(S//NF)`` or ``(TS//REL TO USA, GBR)``."""

    classification: ClassificationLevel
    dissem_controls: List[str] = field(default_factory=list)

    def __str__(self) -> str:
        if not self.dissem_controls:
            return "({})".format(self.classification.value)
        return "({}//{})".format(self.classification.value, "/".join(self.dissem_controls))

    @classmethod
    def parse(cls, raw: object) -> "PortionMarking":
        """Parse a portion-marking string. Raises MarkingError on any problem.

        Accepted shape: ``(LEVEL)`` or ``(LEVEL//CTRL[/CTRL...])`` where LEVEL
        is U, C, S, TS, or TS/SCI and each CTRL is NF/NOFORN, OC/ORCON,
        PROPIN, RELIDO, NOCON, or a single ``REL TO CCC[, CCC...]`` statement.
        """
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            raise MarkingError("portion marking is missing")
        if not isinstance(raw, str):
            raise MarkingError("portion marking must be a string, got {!r}".format(raw))
        m = _PORTION_RE.match(raw.strip())
        if not m:
            raise MarkingError(
                "malformed portion marking {!r}; expected e.g. (U), (S//NF), "
                "(TS//REL TO USA, GBR)".format(raw)
            )
        body = m.group("body").strip()
        parts = body.split("//", 1)
        level = ClassificationLevel.parse(parts[0])
        controls: List[str] = []
        if len(parts) == 2:
            control_tokens = [t for t in parts[1].split("/")]
            if any(not t.strip() for t in control_tokens):
                raise MarkingError("empty dissemination control in {!r}".format(raw))
            controls = validate_dissem_controls(control_tokens)
            if not controls:
                raise MarkingError("marking {!r} has '//' but no controls".format(raw))
        if level is ClassificationLevel.U and controls:
            # U portions carry no dissemination controls in this scheme.
            raise MarkingError(
                "unclassified portion {!r} cannot carry dissemination controls".format(raw)
            )
        return cls(classification=level, dissem_controls=controls)


@dataclass(frozen=True)
class SectionMarking:
    """The full marking applied to one document section at intake time."""

    portion_marking: PortionMarking
    program: Optional[str] = None

    @property
    def classification(self) -> ClassificationLevel:
        return self.portion_marking.classification

    @property
    def dissem_controls(self) -> List[str]:
        return list(self.portion_marking.dissem_controls)

    @classmethod
    def from_raw(cls, portion_marking: object, program: Optional[str] = None) -> "SectionMarking":
        parsed = PortionMarking.parse(portion_marking)
        if program is not None and not str(program).strip():
            raise MarkingError("program identifier, if present, must be non-empty")
        return cls(portion_marking=parsed, program=program)


def highest_level(levels: List[ClassificationLevel]) -> ClassificationLevel:
    if not levels:
        raise MarkingError("cannot compute highest level of an empty marking set")
    return max(levels, key=lambda lv: lv.rank)
