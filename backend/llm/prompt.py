"""Prompt construction. Sources are numbered [S1..Sn] with their portion
markings; the model is told to cite every sentence. Whatever it does, the
claim parser checks the result independently."""

from __future__ import annotations

import hashlib
from typing import List, Tuple

SYSTEM = (
    "You draft intelligence-style answers strictly from the numbered sources provided. "
    "Rules: (1) Every sentence must end with one or more citations in the form [S1] or "
    "[S1][S3], referring only to the source numbers given. (2) Do not state anything the "
    "sources do not support; if the sources are insufficient, say so in a sentence and "
    "cite the closest source. (3) Do not invent source numbers. (4) Write plain sentences "
    "with no headings, lists, or markdown."
)


def build(question: str, hits: List) -> Tuple[str, str, str]:
    lines = ["Question: " + question.strip(), "", "Sources:"]
    for i, h in enumerate(hits, start=1):
        lines.append("[S{}] {} {}".format(i, h.portion_marking, " ".join(h.content.split())))
    user = "\n".join(lines)
    digest = hashlib.sha256((SYSTEM + "\n\n" + user).encode("utf-8")).hexdigest()
    return SYSTEM, user, digest
