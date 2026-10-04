"""Filtered retrieval (Phase 4): PDP builds the filter, the store enforces it
in-query, and every returned hit is independently re-verified against the PDP.

The re-verification is defense in depth, not the access control mechanism —
the filter already ran inside the store query. If a hit ever fails it, the
store and filter have diverged, which is an integrity failure: the search
fails closed with RetrievalIntegrityError rather than returning anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from backend.embedding.embedder import Embedder
from backend.retrieval import pdp
from backend.retrieval.vector_store import SearchHit, VectorStore


class RetrievalIntegrityError(RuntimeError):
    """A chunk that the PDP denies came back from the filtered store query."""


@dataclass(frozen=True)
class FilteredSearchResult:
    user_id: str
    hits: List[SearchHit]
    # Audit trail material (Phase 5 will persist this): the filter that was
    # applied and the per-hit PDP verification decisions.
    filter_summary: Dict[str, object]
    decisions: List[Dict[str, str]]


def filtered_search(
    user: pdp.UserAttributes,
    query_text: str,
    embedder: Embedder,
    store: VectorStore,
    top_k: int = 8,
) -> FilteredSearchResult:
    if not query_text or not query_text.strip():
        raise ValueError("query_text must be non-empty")

    # 1. PDP composes the filter from user attributes + observed controls.
    observed_controls = store.distinct_controls()
    flt = pdp.build_filter(user, observed_controls)

    # 2. The store enforces the filter inside the similarity query.
    query_embedding = embedder.embed_texts([query_text])[0]
    hits = store.search(query_embedding, flt, top_k)

    # 3. Defense in depth: independently re-verify every hit with the PDP.
    decisions: List[Dict[str, str]] = []
    for hit in hits:
        decision = pdp.decide(user, hit.classification, hit.dissem_controls, hit.program)
        decisions.append(
            {
                "chunk_id": hit.chunk_id,
                "allow": str(decision.allow),
                "reason": decision.reason,
            }
        )
        if not decision.allow:
            raise RetrievalIntegrityError(
                "store returned chunk {} ({}) that the PDP denies: {}".format(
                    hit.chunk_id, hit.portion_marking, decision.reason
                )
            )

    return FilteredSearchResult(
        user_id=user.user_id,
        hits=hits,
        filter_summary={
            "allowed_levels": [lv.value for lv in flt.allowed_levels],
            "permitted_controls": list(flt.permitted_controls),
            "allowed_programs": list(flt.allowed_programs),
            "observed_controls": observed_controls,
            "top_k": top_k,
        },
        decisions=decisions,
    )
