"""Policy decision point (Phase 4).

Isolated and independently testable: this module imports only the marking
domain model and the filter type. No database, no web framework, no I/O.

Given a user attribute object and a proposed chunk marking, ``decide`` returns
allow or deny with a reason string for logging. ``build_filter`` composes the
query-level ChunkFilter for a user by running each observed dissemination
control through the same per-control decision, so the filter and the
point-decision can never encode different policy.

SECURITY NOTE — placeholder policy semantics, flagged for the independent
security review required before use with real data:
- ORCON, PROPIN, RELIDO, and NOCON are each modeled as membership in a
  need-to-know group of the same name, standing in for originator-granted
  access, proprietary-information access, disclosure-official release, and
  non-contractor status respectively.
- TS/SCI is modeled as a fifth classification level above TS; individual SCI
  control systems (SI, TK, ...) are not modeled — compartment membership is
  only evaluated against SAP/program markings.
- Citizenship is a single ISO-style trigraph; dual nationals and rel-ability
  rules beyond simple list membership are not modeled.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from backend.models.marking import ClassificationLevel, MarkingError
from backend.retrieval.filters import ChunkFilter, levels_up_to

_TRIGRAPH_RE = re.compile(r"^[A-Z]{3}$")


@dataclass
class UserAttributes:
    user_id: str
    clearance: ClassificationLevel
    citizenship: str
    compartments: List[str] = field(default_factory=list)
    need_to_know_groups: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.user_id, str) or not self.user_id.strip():
            raise MarkingError("user_id is required")
        self.clearance = ClassificationLevel.parse(self.clearance)
        if not isinstance(self.citizenship, str):
            raise MarkingError("citizenship is required")
        self.citizenship = self.citizenship.strip().upper()
        if not _TRIGRAPH_RE.match(self.citizenship):
            raise MarkingError(
                "citizenship must be a 3-letter country trigraph, got {!r}".format(
                    self.citizenship
                )
            )
        for name, values in (
            ("compartments", self.compartments),
            ("need_to_know_groups", self.need_to_know_groups),
        ):
            for v in values:
                if not isinstance(v, str) or not v.strip():
                    raise MarkingError("{} entries must be non-empty strings".format(name))


@dataclass(frozen=True)
class Decision:
    allow: bool
    reason: str

    def __post_init__(self) -> None:
        if not self.reason or not self.reason.strip():
            raise ValueError("every PDP decision must carry a reason string")


def _deny(reason: str) -> Decision:
    return Decision(allow=False, reason=reason)


def _allow(reason: str) -> Decision:
    return Decision(allow=True, reason=reason)


# Controls gated on membership in a need-to-know group of the same name
# (placeholder semantics — see the module security note).
_NTK_GATED_CONTROLS = {
    "ORCON": "originator-granted access",
    "PROPIN": "proprietary-information access",
    "RELIDO": "disclosure-official release",
    "NOCON": "non-contractor status",
}


def control_permitted(user: UserAttributes, control: str) -> Decision:
    """Decide whether one canonical dissemination control is satisfied by the
    user's attributes. Unknown controls are denied (fail closed)."""
    if control == "NOFORN":
        if user.citizenship == "USA":
            return _allow("NOFORN satisfied: citizenship USA")
        return _deny("NOFORN denies non-US person (citizenship {})".format(user.citizenship))
    if control in _NTK_GATED_CONTROLS:
        if control in user.need_to_know_groups:
            return _allow(
                "{} satisfied: {} group present".format(control, _NTK_GATED_CONTROLS[control])
            )
        return _deny(
            "{} denies user without {} group".format(control, _NTK_GATED_CONTROLS[control])
        )
    if control.startswith("REL TO "):
        countries = [c.strip() for c in control[len("REL TO "):].split(",")]
        if user.citizenship in countries:
            return _allow(
                "{} satisfied: citizenship {} in release list".format(control, user.citizenship)
            )
        return _deny(
            "{} denies citizenship {} (not in release list)".format(control, user.citizenship)
        )
    return _deny("unknown dissemination control {!r} is denied by default".format(control))


def decide(
    user: UserAttributes,
    classification: str,
    dissem_controls: List[str],
    program: Optional[str],
) -> Decision:
    """Allow/deny one chunk marking for one user, with a loggable reason.

    Evaluation is fail-closed: an unparseable level, an unsatisfied or unknown
    control, or a program outside the user's compartments each deny.
    """
    try:
        level = ClassificationLevel.parse(classification)
    except MarkingError as exc:
        return _deny("unparseable chunk classification: {}".format(exc))

    if not user.clearance.dominates(level):
        return _deny(
            "clearance {} does not dominate chunk level {}".format(
                user.clearance.value, level.value
            )
        )

    if dissem_controls is None:
        return _deny("chunk has no dissemination control list")
    for control in dissem_controls:
        sub = control_permitted(user, control)
        if not sub.allow:
            return sub

    if program is not None:
        if program not in user.compartments:
            return _deny(
                "program {!r} not in user compartments".format(program)
            )

    satisfied = []
    satisfied.append("clearance {} dominates {}".format(user.clearance.value, level.value))
    if dissem_controls:
        satisfied.append("controls satisfied: {}".format(", ".join(dissem_controls)))
    if program is not None:
        satisfied.append("program {} in compartments".format(program))
    return _allow("; ".join(satisfied))


def build_filter(user: UserAttributes, observed_controls: List[str]) -> ChunkFilter:
    """Compose the query-level filter for a user from PDP decisions.

    ``observed_controls`` is the set of distinct dissemination controls
    currently present in the store (supplied by the retrieval layer). Each is
    admitted to the permitted set only if ``control_permitted`` allows it, so
    the filter is exactly as permissive as the point-decision — no more.
    """
    permitted = [c for c in observed_controls if control_permitted(user, c).allow]
    return ChunkFilter(
        allowed_levels=levels_up_to(user.clearance),
        permitted_controls=permitted,
        allowed_programs=list(user.compartments),
    )
