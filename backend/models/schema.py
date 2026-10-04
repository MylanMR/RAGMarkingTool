"""SQLAlchemy ORM schema for marking metadata.

Every classification column is NOT NULL with no default, at both the ORM and
DDL level (see db/migrations/001_initial.sql). A row cannot exist without an
explicit marking.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

# JSONB on Postgres, plain JSON elsewhere (e.g. sqlite in unit tests).
JsonList = JSON().with_variant(JSONB(), "postgresql")

_LEVELS = "('U','C','S','TS','TS/SCI')"


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Document(Base):
    __tablename__ = "documents"

    id = Column(String(36), primary_key=True, default=_uuid)
    title = Column(Text, nullable=False)
    source_system = Column(Text, nullable=False)
    # Banner classification: highest level of any content in the document.
    classification = Column(String(8), nullable=False)
    dissem_controls = Column(JsonList, nullable=False)
    program = Column(Text, nullable=True)
    content_hash = Column(String(64), nullable=False)
    ingest_date = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    sections = relationship(
        "Section", back_populates="document", order_by="Section.seq",
        cascade="all, delete-orphan",
    )
    chunks = relationship(
        "Chunk", back_populates="document", order_by="Chunk.seq",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint("classification IN " + _LEVELS, name="ck_documents_classification"),
    )


class Section(Base):
    __tablename__ = "sections"

    id = Column(String(36), primary_key=True, default=_uuid)
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    seq = Column(Integer, nullable=False)
    heading = Column(Text, nullable=True)
    content = Column(Text, nullable=False)
    classification = Column(String(8), nullable=False)
    portion_marking = Column(Text, nullable=False)
    dissem_controls = Column(JsonList, nullable=False)
    program = Column(Text, nullable=True)

    document = relationship("Document", back_populates="sections")
    chunks = relationship("Chunk", back_populates="section", order_by="Chunk.seq")

    __table_args__ = (
        CheckConstraint("classification IN " + _LEVELS, name="ck_sections_classification"),
        CheckConstraint("length(trim(portion_marking)) > 0", name="ck_sections_portion_nonempty"),
        UniqueConstraint("document_id", "seq", name="uq_sections_document_seq"),
    )


class QueryAuditLog(Base):
    """One row per query attempt — served, rejected, or failed. Scalar columns
    cover the common audit filters; the JSON columns keep full fidelity
    (attributes evaluated, filter applied, markings returned, PDP reasons)."""

    __tablename__ = "query_audit_log"

    id = Column(String(36), primary_key=True, default=_uuid)
    ts = Column(DateTime(timezone=True), nullable=False)
    user_id = Column(Text, nullable=False, index=True)
    clearance = Column(String(8), nullable=True)   # null when attributes were rejected
    citizenship = Column(String(3), nullable=True)
    outcome = Column(String(32), nullable=False, index=True)
    query_text = Column(Text, nullable=False)
    top_k = Column(Integer, nullable=True)
    result_count = Column(Integer, nullable=False)
    user_attributes = Column(JsonList, nullable=False)
    filter_summary = Column(JsonList, nullable=True)
    returned_chunks = Column(JsonList, nullable=True)
    decisions = Column(JsonList, nullable=True)
    detail = Column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "outcome IN ('ok','integrity_failure','rejected_attributes')",
            name="ck_audit_outcome",
        ),
    )


class Chunk(Base):
    __tablename__ = "chunks"

    chunk_id = Column(String(36), primary_key=True)
    parent_doc_id = Column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    section_id = Column(String(36), ForeignKey("sections.id", ondelete="CASCADE"), nullable=False)
    seq = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    classification = Column(String(8), nullable=False)
    portion_marking = Column(Text, nullable=False)
    dissem_controls = Column(JsonList, nullable=False)
    program = Column(Text, nullable=True)
    source_system = Column(Text, nullable=False)
    ingest_date = Column(DateTime(timezone=True), nullable=False)
    content_hash = Column(String(64), nullable=False)

    document = relationship("Document", back_populates="chunks")
    section = relationship("Section", back_populates="chunks")

    __table_args__ = (
        CheckConstraint("classification IN " + _LEVELS, name="ck_chunks_classification"),
        CheckConstraint("length(trim(portion_marking)) > 0", name="ck_chunks_portion_nonempty"),
        UniqueConstraint("parent_doc_id", "seq", name="uq_chunks_document_seq"),
    )
