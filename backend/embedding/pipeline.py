"""Phase 3 pipeline: embed a document's chunks and write them to the vector
store with their marking metadata attached.

The chunks table is the source of truth for markings; the pipeline copies the
marking onto every VectorRecord and the store re-validates it on upsert, so an
unmarked vector cannot be written by any path.
"""

from typing import List

from sqlalchemy.orm import Session

from backend.embedding.embedder import Embedder
from backend.models import schema
from backend.models.marking import MarkingError
from backend.retrieval.vector_store import VectorRecord, VectorStore


class DocumentNotFound(LookupError):
    pass


def embed_document_chunks(
    db: Session, doc_id: str, embedder: Embedder, store: VectorStore
) -> int:
    """Embed every chunk of one document and upsert into the vector store.

    Idempotent: re-running re-embeds and overwrites by chunk_id. Returns the
    number of chunks embedded.
    """
    chunks: List[schema.Chunk] = (
        db.query(schema.Chunk)
        .filter(schema.Chunk.parent_doc_id == doc_id)
        .order_by(schema.Chunk.seq)
        .all()
    )
    if not chunks:
        raise DocumentNotFound("no chunks found for document {}".format(doc_id))

    # Defense in depth: the DB schema already forbids unmarked chunks, but the
    # pipeline refuses to embed anything unmarked regardless of storage layer.
    for chunk in chunks:
        if not chunk.classification or not chunk.portion_marking:
            raise MarkingError(
                "chunk {} is missing marking metadata; refusing to embed".format(chunk.chunk_id)
            )

    embeddings = embedder.embed_texts([c.content for c in chunks])
    records = [
        VectorRecord(
            chunk_id=chunk.chunk_id,
            parent_doc_id=chunk.parent_doc_id,
            content=chunk.content,
            embedding=embedding,
            classification=chunk.classification,
            portion_marking=chunk.portion_marking,
            dissem_controls=list(chunk.dissem_controls),
            program=chunk.program,
            content_hash=chunk.content_hash,
        )
        for chunk, embedding in zip(chunks, embeddings)
    ]
    return store.upsert(records)
