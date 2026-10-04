"""Vector stores that carry marking metadata with every vector.

Invariants enforced here:

- A record cannot be upserted without a complete, valid marking (level,
  portion marking, dissemination controls). There is no default path.
- ``search`` requires a ChunkFilter; there is no unfiltered search method.
- Filtering happens at query level — candidates are restricted *before*
  similarity ranking — never by truncating an unfiltered result set.

PgVectorStore is the production path (Postgres + pgvector, migration 002).
InMemoryVectorStore has identical semantics for tests and development.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol

from sqlalchemy import text
from sqlalchemy.engine import Engine

from backend.models.marking import ClassificationLevel, MarkingError
from backend.retrieval.filters import ChunkFilter


@dataclass(frozen=True)
class VectorRecord:
    """One chunk's embedding plus the marking metadata that must travel with it."""

    chunk_id: str
    parent_doc_id: str
    content: str
    embedding: List[float]
    classification: str
    portion_marking: str
    dissem_controls: List[str]
    program: Optional[str]
    content_hash: str


@dataclass(frozen=True)
class SearchHit:
    chunk_id: str
    parent_doc_id: str
    content: str
    score: float
    classification: str
    portion_marking: str
    dissem_controls: List[str]
    program: Optional[str]
    content_hash: str


def _validate_record(record: VectorRecord, expected_dim: Optional[int]) -> None:
    ClassificationLevel.parse(record.classification)  # raises MarkingError
    if not record.portion_marking or not record.portion_marking.strip():
        raise MarkingError(
            "chunk {} has no portion marking; refusing to store vector".format(record.chunk_id)
        )
    if record.dissem_controls is None or not isinstance(record.dissem_controls, list):
        raise MarkingError(
            "chunk {} has no dissemination control list".format(record.chunk_id)
        )
    if not record.embedding:
        raise ValueError("chunk {} has an empty embedding".format(record.chunk_id))
    if expected_dim is not None and len(record.embedding) != expected_dim:
        raise ValueError(
            "chunk {} embedding dimension {} != store dimension {}".format(
                record.chunk_id, len(record.embedding), expected_dim
            )
        )


class VectorStore(Protocol):
    def upsert(self, records: List[VectorRecord]) -> int:
        ...

    def search(self, query_embedding: List[float], flt: ChunkFilter, top_k: int) -> List[SearchHit]:
        ...

    def distinct_controls(self) -> List[str]:
        """All distinct dissemination-control values currently stored. The
        retrieval layer feeds these to the PDP to compose the query filter."""
        ...


class InMemoryVectorStore:
    """Brute-force store with the same query-level filtering semantics as
    the pgvector path. For tests and development only."""

    def __init__(self, dim: Optional[int] = None):
        self.dim = dim
        self._records: Dict[str, VectorRecord] = {}

    def __len__(self) -> int:
        return len(self._records)

    def upsert(self, records: List[VectorRecord]) -> int:
        # Validate everything before writing anything: no partial upserts.
        for record in records:
            _validate_record(record, self.dim)
            if self.dim is None:
                self.dim = len(record.embedding)
        for record in records:
            self._records[record.chunk_id] = record
        return len(records)

    def distinct_controls(self) -> List[str]:
        return sorted({c for r in self._records.values() for c in r.dissem_controls})

    def search(self, query_embedding: List[float], flt: ChunkFilter, top_k: int) -> List[SearchHit]:
        if flt is None:
            raise MarkingError("search requires a ChunkFilter; unfiltered search is not allowed")
        if top_k < 1:
            raise ValueError("top_k must be >= 1")
        # Filter FIRST, then rank: query-level filtering, not post-retrieval.
        candidates = [
            r
            for r in self._records.values()
            if flt.matches(r.classification, r.dissem_controls, r.program)
        ]
        scored = sorted(
            candidates,
            key=lambda r: _dot(query_embedding, r.embedding),
            reverse=True,
        )[:top_k]
        return [
            SearchHit(
                chunk_id=r.chunk_id,
                parent_doc_id=r.parent_doc_id,
                content=r.content,
                score=_dot(query_embedding, r.embedding),
                classification=r.classification,
                portion_marking=r.portion_marking,
                dissem_controls=list(r.dissem_controls),
                program=r.program,
                content_hash=r.content_hash,
            )
            for r in scored
        ]


def _dot(a: List[float], b: List[float]) -> float:
    if len(a) != len(b):
        raise ValueError("embedding dimension mismatch: {} vs {}".format(len(a), len(b)))
    return sum(x * y for x, y in zip(a, b))


class PgVectorStore:
    """pgvector-backed store. The embedding lives on the chunks row itself
    (migration 002), so marking metadata and vector can never diverge, and
    the marking filter is part of the SQL query's WHERE clause."""

    def __init__(self, engine: Engine, dim: int = 384):
        self.engine = engine
        self.dim = dim

    def upsert(self, records: List[VectorRecord]) -> int:
        for record in records:
            _validate_record(record, self.dim)
        with self.engine.begin() as conn:
            for record in records:
                result = conn.execute(
                    text(
                        "UPDATE chunks SET embedding = CAST(:vec AS vector) "
                        "WHERE chunk_id = :chunk_id"
                    ),
                    {"vec": _to_pgvector(record.embedding), "chunk_id": record.chunk_id},
                )
                if result.rowcount != 1:
                    # The marked chunk row must already exist; an embedding
                    # can never be stored without its marking metadata.
                    raise MarkingError(
                        "chunk {} has no chunks row; refusing to store orphan "
                        "vector".format(record.chunk_id)
                    )
        return len(records)

    def distinct_controls(self) -> List[str]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT DISTINCT jsonb_array_elements_text(dissem_controls) AS c "
                    "FROM chunks ORDER BY c"
                )
            ).all()
        return [row[0] for row in rows]

    def search(self, query_embedding: List[float], flt: ChunkFilter, top_k: int) -> List[SearchHit]:
        if flt is None:
            raise MarkingError("search requires a ChunkFilter; unfiltered search is not allowed")
        if top_k < 1:
            raise ValueError("top_k must be >= 1")
        if not flt.allowed_levels:
            return []

        conditions = [
            "embedding IS NOT NULL",
            "classification = ANY(:levels)",
            # Chunk's controls must be a subset of the permitted controls.
            "dissem_controls <@ CAST(:permitted AS jsonb)",
        ]
        params = {
            "levels": [lv.value for lv in flt.allowed_levels],
            "permitted": json.dumps(flt.permitted_controls),
            "qvec": _to_pgvector(query_embedding),
            "top_k": top_k,
        }
        if flt.allowed_programs:
            conditions.append("(program IS NULL OR program = ANY(:programs))")
            params["programs"] = flt.allowed_programs
        else:
            conditions.append("program IS NULL")

        sql = text(
            "SELECT chunk_id, parent_doc_id, content, classification, "
            "       portion_marking, dissem_controls, program, content_hash, "
            "       1 - (embedding <=> CAST(:qvec AS vector)) AS score "
            "FROM chunks "
            "WHERE " + " AND ".join(conditions) + " "
            "ORDER BY embedding <=> CAST(:qvec AS vector) "
            "LIMIT :top_k"
        )
        with self.engine.connect() as conn:
            rows = conn.execute(sql, params).mappings().all()
        return [
            SearchHit(
                chunk_id=str(row["chunk_id"]),
                parent_doc_id=str(row["parent_doc_id"]),
                content=row["content"],
                score=float(row["score"]),
                classification=row["classification"],
                portion_marking=row["portion_marking"],
                dissem_controls=list(row["dissem_controls"]),
                program=row["program"],
                content_hash=row["content_hash"],
            )
            for row in rows
        ]


def _to_pgvector(embedding: List[float]) -> str:
    return "[" + ",".join(repr(float(v)) for v in embedding) + "]"


_memory_store: Optional[InMemoryVectorStore] = None


def get_vector_store() -> VectorStore:
    """FastAPI dependency for the configured vector store.

    VECTOR_STORE=memory selects a process-lifetime in-memory store (dev only:
    embeddings vanish on restart — re-run the embed step). Default: pgvector.
    """
    import os

    if os.environ.get("VECTOR_STORE", "pgvector").lower() == "memory":
        global _memory_store
        if _memory_store is None:
            _memory_store = InMemoryVectorStore()
        return _memory_store
    from backend.db.database import get_engine

    return PgVectorStore(get_engine())
