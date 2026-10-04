"""Split a model draft into sentence-level claims and resolve citations.

A citation is [S<n>] (also [S1, S3] or [S1][S3]). A reference to a source
number that was not supplied is recorded as an invalid (fabricated) ref and
never counts as support. A claim with no valid citation is 'uncited'.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

_REF_GROUP = re.compile(r"\[\s*(S\s*\d+(?:\s*[,;]\s*S?\s*\d+)*)\s*\]", re.I)
_NUM = re.compile(r"\d+")
_SPLIT = re.compile(r"(?<=[.!?])\s+(?!\[S)|(?<=\])\s+(?=[A-Z\"(])")
_BULLET = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)])\s+")


@dataclass
class ParsedClaim:
    text: str
    cited: List[int] = field(default_factory=list)
    invalid: List[str] = field(default_factory=list)

    @property
    def kind(self) -> str:
        return "cited" if self.cited else "uncited"


def parse(draft: str, n_sources: int) -> List[ParsedClaim]:
    out: List[ParsedClaim] = []
    for para in (draft or "").splitlines():
        para = _BULLET.sub("", para.strip())
        if not para:
            continue
        for piece in _SPLIT.split(para):
            piece = piece.strip()
            if not piece:
                continue
            cited: List[int] = []
            invalid: List[str] = []
            for grp in _REF_GROUP.findall(piece):
                for num in _NUM.findall(grp):
                    n = int(num)
                    if 1 <= n <= n_sources:
                        if n not in cited:
                            cited.append(n)
                    elif "S{}".format(n) not in invalid:
                        invalid.append("S{}".format(n))
            text = re.sub(r"\s+([.!?,;:])", r"\1", _REF_GROUP.sub("", piece)).strip()
            text = re.sub(r"\s{2,}", " ", text)
            if text:
                out.append(ParsedClaim(text=text, cited=cited, invalid=invalid))
    return out
