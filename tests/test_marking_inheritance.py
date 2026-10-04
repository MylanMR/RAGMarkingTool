"""Unit tests for the marking-inheriting chunker (Phase 2).

Core properties under test:
- every chunk carries its source section's exact marking;
- a document with any unmarked section produces zero chunks (no partial output);
- chunks never span section boundaries;
- there is no default-marking code path.
"""

import hashlib
from datetime import datetime, timezone

import pytest

from backend.chunking.marked_chunker import (
    MarkedChunk,
    MarkedSection,
    chunk_document,
    sha256_hex,
)
from backend.models.marking import MarkingError, SectionMarking

NOW = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)


def section(text: str, marking: str, program=None, heading=None) -> MarkedSection:
    return MarkedSection(
        content=text, marking=SectionMarking.from_raw(marking, program), heading=heading
    )


def chunk(sections, **kwargs):
    defaults = dict(
        parent_doc_id="doc-1", sections=sections, source_system="unit-test", ingest_date=NOW
    )
    defaults.update(kwargs)
    return chunk_document(**defaults)


class TestMarkingInheritance:
    def test_every_chunk_inherits_its_section_marking(self):
        chunks = chunk(
            [
                section("Unclassified overview text.", "(U)"),
                section("Secret noforn details.", "(S//NF)"),
                section("Top secret releasable analysis.", "(TS//REL TO USA, GBR)"),
            ]
        )
        assert len(chunks) == 3
        assert [c.classification for c in chunks] == ["U", "S", "TS"]
        assert chunks[0].portion_marking == "(U)"
        assert chunks[0].dissem_controls == []
        assert chunks[1].portion_marking == "(S//NOFORN)"
        assert chunks[1].dissem_controls == ["NOFORN"]
        assert chunks[2].dissem_controls == ["REL TO USA, GBR"]

    def test_long_section_all_chunks_marked(self):
        long_text = " ".join(
            "Sentence number {} about a secret topic.".format(i) for i in range(200)
        )
        chunks = chunk([section(long_text, "(S//NF)", program="ALPHA")], max_chars=300)
        assert len(chunks) > 1
        for c in chunks:
            assert c.classification == "S"
            assert c.portion_marking == "(S//NOFORN)"
            assert c.dissem_controls == ["NOFORN"]
            assert c.program == "ALPHA"
            assert len(c.content) <= 300

    def test_chunks_never_span_sections(self):
        chunks = chunk(
            [
                section("Alpha alpha alpha. " * 30, "(U)"),
                section("Bravo bravo bravo. " * 30, "(S)"),
            ],
            max_chars=200,
        )
        for c in chunks:
            if c.section_index == 0:
                assert "Bravo" not in c.content
                assert c.classification == "U"
            else:
                assert "Alpha" not in c.content
                assert c.classification == "S"

    def test_seq_is_contiguous_and_content_reassembles(self):
        chunks = chunk([section("Some text here.", "(C)"), section("More text.", "(C)")])
        assert [c.seq for c in chunks] == list(range(len(chunks)))


class TestRejection:
    def test_unmarked_section_yields_zero_chunks(self):
        good = section("Fine text.", "(U)")
        bad = MarkedSection(content="Orphan text.", marking=None)  # type: ignore[arg-type]
        with pytest.raises(MarkingError):
            chunk([good, bad])
        # Order must not matter: failure before any output either way.
        with pytest.raises(MarkingError):
            chunk([bad, good])

    def test_marking_of_wrong_type_rejected(self):
        bad = MarkedSection(content="Text.", marking="(S//NF)")  # type: ignore[arg-type]
        with pytest.raises(MarkingError):
            chunk([bad])

    def test_empty_section_content_rejected(self):
        with pytest.raises(MarkingError):
            chunk([section("Fine.", "(U)"), MarkedSection(content="   ", marking=SectionMarking.from_raw("(U)"))])

    def test_empty_document_rejected(self):
        with pytest.raises(MarkingError):
            chunk([])

    def test_missing_parent_doc_id_rejected(self):
        with pytest.raises(MarkingError):
            chunk([section("Text.", "(U)")], parent_doc_id="  ")

    def test_no_default_marking_constructor(self):
        # MarkedChunk cannot be constructed without explicit marking fields.
        with pytest.raises(TypeError):
            MarkedChunk(  # type: ignore[call-arg]
                chunk_id="x",
                parent_doc_id="doc-1",
                section_index=0,
                seq=0,
                content="text",
            )


class TestIntegrity:
    def test_content_hash_is_sha256_of_content(self):
        (c,) = chunk([section("Hash me exactly.", "(S)")])
        assert c.content_hash == hashlib.sha256(c.content.encode("utf-8")).hexdigest()
        assert sha256_hex("Hash me exactly.") == c.content_hash

    def test_provenance_fields_set(self):
        (c,) = chunk([section("Text.", "(C)")])
        assert c.parent_doc_id == "doc-1"
        assert c.source_system == "unit-test"
        assert c.ingest_date == NOW
        assert c.chunk_id
