"""Chunker that enforces marking inheritance.

Rules:
- Chunks never cross a section boundary, because the section is the marking
  boundary.
- Every chunk is created with its section's full marking, at creation time.
- If any section's marking is missing or malformed, the whole document is
  rejected before any chunk is produced (no partial output).
- There is no default marking path anywhere in this module.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from backend.models.marking import MarkingError, SectionMarking


@dataclass(frozen=True)
class MarkedSection:
    """Input to the chunker: one section of text plus its parsed marking."""

    content: str
    marking: SectionMarking
    heading: Optional[str] = None


@dataclass(frozen=True)
class MarkedChunk:
    """Output of the chunker. All marking fields are required; none default."""

    chunk_id: str
    parent_doc_id: str
    section_index: int
    seq: int
    content: str
    classification: str
    portion_marking: str
    dissem_controls: List[str]
    program: Optional[str]
    source_system: str
    ingest_date: datetime
    content_hash: str


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _split_text(text: str, max_chars: int) -> List[str]:
    """Split text into pieces of at most max_chars, preferring paragraph,
    then sentence, then word boundaries. Never returns an empty piece."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    pieces: List[str] = []
    paragraphs = re.split(r"\n\s*\n", text)
    buffer = ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        candidate = (buffer + "\n\n" + para) if buffer else para
        if len(candidate) <= max_chars:
            buffer = candidate
            continue
        if buffer:
            pieces.append(buffer)
            buffer = ""
        if len(para) <= max_chars:
            buffer = para
        else:
            pieces.extend(_split_long_block(para, max_chars))
    if buffer:
        pieces.append(buffer)
    return pieces


def _split_long_block(block: str, max_chars: int) -> List[str]:
    """Split a single oversized block on sentence/word boundaries."""
    sentences = re.split(r"(?<=[.!?])\s+", block)
    pieces: List[str] = []
    buffer = ""
    for sentence in sentences:
        candidate = (buffer + " " + sentence) if buffer else sentence
        if len(candidate) <= max_chars:
            buffer = candidate
            continue
        if buffer:
            pieces.append(buffer)
            buffer = ""
        if len(sentence) <= max_chars:
            buffer = sentence
        else:
            # Fall back to word-boundary packing for a run-on sentence.
            words = sentence.split(" ")
            wbuf = ""
            for word in words:
                wcand = (wbuf + " " + word) if wbuf else word
                if len(wcand) <= max_chars:
                    wbuf = wcand
                else:
                    if wbuf:
                        pieces.append(wbuf)
                    # A single word longer than max_chars gets hard-split.
                    while len(word) > max_chars:
                        pieces.append(word[:max_chars])
                        word = word[max_chars:]
                    wbuf = word
            if wbuf:
                buffer = wbuf
    if buffer:
        pieces.append(buffer)
    return pieces


def chunk_document(
    parent_doc_id: str,
    sections: List[MarkedSection],
    source_system: str,
    ingest_date: datetime,
    max_chars: int = 1200,
) -> List[MarkedChunk]:
    """Chunk a document, attaching each section's marking to every chunk.

    Validates every section's marking before producing any chunk, so a marking
    failure in section N can never leave chunks from sections 0..N-1 behind.
    """
    if not parent_doc_id or not str(parent_doc_id).strip():
        raise MarkingError("parent_doc_id is required")
    if not sections:
        raise MarkingError("document has no sections to chunk")
    if max_chars < 50:
        raise ValueError("max_chars must be at least 50")

    # Pass 1: validate all markings up front. MarkedSection carries a parsed
    # SectionMarking, but guard against None sneaking in from callers.
    for idx, section in enumerate(sections):
        if section.marking is None:
            raise MarkingError("section {} has no marking; refusing to chunk".format(idx))
        if not isinstance(section.marking, SectionMarking):
            raise MarkingError(
                "section {} marking is not a SectionMarking: {!r}".format(idx, section.marking)
            )
        if not section.content or not section.content.strip():
            raise MarkingError("section {} has no content".format(idx))

    # Pass 2: split and emit, inheriting the section marking verbatim.
    chunks: List[MarkedChunk] = []
    seq = 0
    for idx, section in enumerate(sections):
        marking = section.marking
        for piece in _split_text(section.content, max_chars):
            chunks.append(
                MarkedChunk(
                    chunk_id=str(uuid.uuid4()),
                    parent_doc_id=parent_doc_id,
                    section_index=idx,
                    seq=seq,
                    content=piece,
                    classification=marking.classification.value,
                    portion_marking=str(marking.portion_marking),
                    dissem_controls=marking.dissem_controls,
                    program=marking.program,
                    source_system=source_system,
                    ingest_date=ingest_date,
                    content_hash=sha256_hex(piece),
                )
            )
            seq += 1

    if not chunks:
        raise MarkingError("chunking produced no chunks; document content is empty")
    return chunks
