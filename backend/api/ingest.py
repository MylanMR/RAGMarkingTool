"""Document intake API (Phase 1) wired to the marking-inheriting chunker (Phase 2).

Every section must arrive with an explicit portion marking; the request is
rejected otherwise. The banner classification must dominate every section
level. There are no default markings anywhere in this pipeline.
"""

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from backend.chunking.marked_chunker import MarkedSection, chunk_document, sha256_hex
from backend.auth.deps import Principal, scaffold_or_roles
from backend.db.database import get_session
from backend.governance import chain
from backend.policy import catalog as policy_catalog, store as policy_store
from typing import Optional as _Opt
from backend.embedding.embedder import Embedder, get_embedder
from backend.embedding.pipeline import DocumentNotFound, embed_document_chunks
from backend.models import schema
from backend.retrieval.vector_store import VectorStore, get_vector_store
from backend.models.marking import (
    ClassificationLevel,
    MarkingError,
    SectionMarking,
    highest_level,
    validate_dissem_controls,
)

router = APIRouter(prefix="/ingest", tags=["ingest"])


class SectionIn(BaseModel):
    heading: Optional[str] = None
    content: str = Field(..., min_length=1)
    # Required, no default: a section without a portion marking is rejected.
    portion_marking: str = Field(..., min_length=3, examples=["(S//NF)"])
    program: Optional[str] = None

    @field_validator("content")
    @classmethod
    def content_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("section content must not be blank")
        return v


class DocumentIn(BaseModel):
    title: str = Field(..., min_length=1)
    source_system: str = Field(..., min_length=1)
    # Banner classification for the whole document. Required, no default.
    classification: str = Field(..., examples=["S"])
    dissem_controls: List[str] = Field(default_factory=list)
    program: Optional[str] = None
    sections: List[SectionIn] = Field(..., min_length=1)


class EmbedOut(BaseModel):
    doc_id: str
    chunks_embedded: int
    embedding_dim: int


class ChunkOut(BaseModel):
    chunk_id: str
    seq: int
    classification: str
    portion_marking: str
    dissem_controls: List[str]
    content_hash: str


class DocumentOut(BaseModel):
    id: str
    title: str
    classification: str
    dissem_controls: List[str]
    section_count: int
    chunk_count: int
    chunks: List[ChunkOut]


@router.post("/documents/{doc_id}/embed", response_model=EmbedOut)
def embed_document(
    doc_id: str,
    db: Session = Depends(get_session),
    embedder: Embedder = Depends(get_embedder),
    store: VectorStore = Depends(get_vector_store),
    principal: _Opt[Principal] = Depends(scaffold_or_roles("author", "admin")),
) -> EmbedOut:
    """Phase 3: embed a document's chunks into the vector store, marking
    metadata attached. Idempotent; safe to re-run after re-ingest."""
    try:
        count = embed_document_chunks(db, doc_id, embedder, store)
    except DocumentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except MarkingError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return EmbedOut(doc_id=doc_id, chunks_embedded=count, embedding_dim=embedder.dim)


@router.post("/documents", response_model=DocumentOut, status_code=201)
def ingest_document(
    payload: DocumentIn,
    db: Session = Depends(get_session),
    principal: _Opt[Principal] = Depends(scaffold_or_roles("author", "admin")),
) -> DocumentOut:
    # Parse and validate all markings before touching the database.
    try:
        banner = ClassificationLevel.parse(payload.classification)
        banner_controls = validate_dissem_controls(payload.dissem_controls)
        markings = [
            SectionMarking.from_raw(s.portion_marking, s.program or payload.program)
            for s in payload.sections
        ]
    except MarkingError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    max_section_level = highest_level([m.classification for m in markings])
    if not banner.dominates(max_section_level):
        raise HTTPException(
            status_code=422,
            detail=(
                "banner classification {} does not dominate highest section "
                "level {}".format(banner.value, max_section_level.value)
            ),
        )

    if principal is not None:
        # Production mode: nobody ingests above their own clearance or above
        # the accredited system high.
        system_high = policy_store.current(db).system_high
        if policy_catalog.level_rank(banner.value) > policy_catalog.level_rank(system_high):
            raise HTTPException(status_code=403, detail=(
                "banner {} exceeds the system high ({})".format(banner.value, system_high)))
        if not ClassificationLevel.parse(principal.user.clearance).dominates(banner):
            raise HTTPException(status_code=403, detail=(
                "cannot ingest a {} document with {} clearance".format(
                    banner.value, principal.user.clearance)))

    doc_id = str(uuid.uuid4())
    ingest_date = datetime.now(timezone.utc)
    full_text = "\n\n".join(s.content for s in payload.sections)

    marked_sections = [
        MarkedSection(content=s.content, marking=m, heading=s.heading)
        for s, m in zip(payload.sections, markings)
    ]
    try:
        chunks = chunk_document(
            parent_doc_id=doc_id,
            sections=marked_sections,
            source_system=payload.source_system,
            ingest_date=ingest_date,
        )
    except MarkingError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    doc_row = schema.Document(
        id=doc_id,
        title=payload.title,
        source_system=payload.source_system,
        classification=banner.value,
        dissem_controls=banner_controls,
        program=payload.program,
        content_hash=sha256_hex(full_text),
        ingest_date=ingest_date,
    )
    db.add(doc_row)

    section_ids: List[str] = []
    for idx, (section, marking) in enumerate(zip(payload.sections, markings)):
        section_id = str(uuid.uuid4())
        section_ids.append(section_id)
        db.add(
            schema.Section(
                id=section_id,
                document_id=doc_id,
                seq=idx,
                heading=section.heading,
                content=section.content,
                classification=marking.classification.value,
                portion_marking=str(marking.portion_marking),
                dissem_controls=marking.dissem_controls,
                program=marking.program,
            )
        )

    for chunk in chunks:
        db.add(
            schema.Chunk(
                chunk_id=chunk.chunk_id,
                parent_doc_id=chunk.parent_doc_id,
                section_id=section_ids[chunk.section_index],
                seq=chunk.seq,
                content=chunk.content,
                classification=chunk.classification,
                portion_marking=chunk.portion_marking,
                dissem_controls=chunk.dissem_controls,
                program=chunk.program,
                source_system=chunk.source_system,
                ingest_date=chunk.ingest_date,
                content_hash=chunk.content_hash,
            )
        )

    db.commit()

    return DocumentOut(
        id=doc_id,
        title=payload.title,
        classification=banner.value,
        dissem_controls=banner_controls,
        section_count=len(payload.sections),
        chunk_count=len(chunks),
        chunks=[
            ChunkOut(
                chunk_id=c.chunk_id,
                seq=c.seq,
                classification=c.classification,
                portion_marking=c.portion_marking,
                dissem_controls=c.dissem_controls,
                content_hash=c.content_hash,
            )
            for c in chunks
        ],
    )
