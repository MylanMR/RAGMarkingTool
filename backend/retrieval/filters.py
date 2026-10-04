"""Marking filters applied inside vector-store queries.

A ChunkFilter is deny-by-default in every dimension:

- ``allowed_levels`` is required; an empty list matches nothing.
- A chunk's dissemination controls must be a subset of ``permitted_controls``;
  a chunk carrying any control not explicitly permitted is excluded.
- A chunk with a program marking is excluded unless that program appears in
  ``allowed_programs``.

Phase 4's policy decision point is responsible for constructing these filters
from user attributes; this module only defines the filter semantics that the
stores enforce at query level.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from backend.models.marking import (
    ClassificationLevel,
    MarkingError,
    normalize_dissem_control,
)


@dataclass
class ChunkFilter:
    allowed_levels: List[ClassificationLevel]
    permitted_controls: List[str]
    allowed_programs: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.allowed_levels = [ClassificationLevel.parse(lv) for lv in self.allowed_levels]
        self.permitted_controls = [
            normalize_dissem_control(c) for c in self.permitted_controls
        ]
        for p in self.allowed_programs:
            if not isinstance(p, str) or not p.strip():
                raise MarkingError("allowed_programs entries must be non-empty strings")

    def matches(
        self,
        classification: str,
        dissem_controls: List[str],
        program: Optional[str],
    ) -> bool:
        """Deny-by-default match of one chunk's marking against this filter."""
        try:
            level = ClassificationLevel.parse(classification)
        except MarkingError:
            return False  # unparseable marking never matches
        if level not in self.allowed_levels:
            return False
        if dissem_controls is None:
            return False
        if not set(dissem_controls).issubset(set(self.permitted_controls)):
            return False
        if program is not None and program not in self.allowed_programs:
            return False
        return True


def levels_up_to(ceiling: ClassificationLevel) -> List[ClassificationLevel]:
    """All levels dominated by ``ceiling``, e.g. S -> [U, C, S]."""
    return [lv for lv in ClassificationLevel if ceiling.dominates(lv)]
