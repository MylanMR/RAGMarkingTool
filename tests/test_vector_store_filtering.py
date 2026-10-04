"""Phase 3 unit tests: embedder determinism and vector-store filtering.

The load-bearing test is TestQueryLevelFiltering.test_filter_is_not_post_retrieval_truncation:
it proves the marking filter restricts candidates *before* similarity ranking,
because a post-retrieval truncation of the unfiltered top-k would return fewer
(or zero) authorized hits.
"""

import pytest

from backend.embedding.embedder import HashingEmbedder
from backend.models.marking import ClassificationLevel, MarkingError
from backend.retrieval.filters import ChunkFilter, levels_up_to
from backend.retrieval.vector_store import InMemoryVectorStore, VectorRecord

EMB = HashingEmbedder(dim=64)


def record(chunk_id, content, classification, controls=None, program=None):
    return VectorRecord(
        chunk_id=chunk_id,
        parent_doc_id="doc-1",
        content=content,
        embedding=EMB.embed_texts([content])[0],
        classification=classification,
        portion_marking="({})".format(classification),
        dissem_controls=controls if controls is not None else [],
        program=program,
        content_hash="x" * 64,
    )


def query(text):
    return EMB.embed_texts([text])[0]


def flt(levels, controls=(), programs=()):
    return ChunkFilter(
        allowed_levels=list(levels),
        permitted_controls=list(controls),
        allowed_programs=list(programs),
    )


class TestHashingEmbedder:
    def test_deterministic(self):
        a = EMB.embed_texts(["the quick brown fox"])[0]
        b = EMB.embed_texts(["the quick brown fox"])[0]
        assert a == b
        assert len(a) == 64

    def test_similar_texts_score_higher(self):
        base = query("satellite imagery of the northern harbor")
        near = record("n", "imagery of the northern harbor", "U")
        far = record("f", "quarterly budget spreadsheet totals", "U")
        store = InMemoryVectorStore()
        store.upsert([near, far])
        hits = store.search(base, flt(["U"]), top_k=2)
        assert hits[0].chunk_id == "n"

    def test_empty_text_rejected(self):
        with pytest.raises(ValueError):
            EMB.embed_texts(["   "])


class TestUpsertGuards:
    def test_unmarked_record_rejected_nothing_written(self):
        store = InMemoryVectorStore()
        good = record("g", "fine text", "U")
        bad = record("b", "bad text", "")  # no classification
        with pytest.raises(MarkingError):
            store.upsert([good, bad])
        assert len(store) == 0  # validate-all-before-write

    def test_blank_portion_marking_rejected(self):
        base = record("p", "text", "S")
        bad = VectorRecord(**{**base.__dict__, "portion_marking": "  "})
        store = InMemoryVectorStore()
        with pytest.raises(MarkingError):
            store.upsert([bad])

    def test_dimension_mismatch_rejected(self):
        store = InMemoryVectorStore(dim=64)
        bad = VectorRecord(**{**record("d", "text", "U").__dict__, "embedding": [0.1] * 32})
        with pytest.raises(ValueError):
            store.upsert([bad])

    def test_upsert_is_idempotent_by_chunk_id(self):
        store = InMemoryVectorStore()
        store.upsert([record("same", "text one", "U")])
        store.upsert([record("same", "text one updated", "U")])
        assert len(store) == 1


class TestQueryLevelFiltering:
    def test_filter_is_not_post_retrieval_truncation(self):
        """The nearest neighbors are all S//NOFORN; a U-only filter must still
        fill top_k with U chunks. Post-retrieval truncation would return []."""
        store = InMemoryVectorStore()
        q = "harbor imagery analysis report"
        store.upsert(
            [
                record("s1", "harbor imagery analysis report alpha", "S", ["NOFORN"]),
                record("s2", "harbor imagery analysis report bravo", "S", ["NOFORN"]),
                record("s3", "harbor imagery analysis report charlie", "S", ["NOFORN"]),
                record("u1", "harbor shipping schedule", "U"),
                record("u2", "weather along the coast", "U"),
            ]
        )
        unfiltered_top = store.search(
            query(q), flt(["U", "C", "S"], controls=["NOFORN"]), top_k=3
        )
        assert {h.chunk_id for h in unfiltered_top} == {"s1", "s2", "s3"}

        u_only = store.search(query(q), flt(["U"]), top_k=3)
        assert [h.classification for h in u_only] == ["U", "U"]
        assert {h.chunk_id for h in u_only} == {"u1", "u2"}

    def test_empty_allowed_levels_matches_nothing(self):
        store = InMemoryVectorStore()
        store.upsert([record("u1", "public text", "U")])
        assert store.search(query("public text"), flt([]), top_k=5) == []

    def test_controls_are_subset_matched(self):
        store = InMemoryVectorStore()
        store.upsert(
            [
                record("plain", "report text", "S"),
                record("nf", "report text noforn", "S", ["NOFORN"]),
                record("nf_oc", "report text noforn orcon", "S", ["NOFORN", "ORCON"]),
            ]
        )
        hits = store.search(query("report text"), flt(["S"], controls=["NOFORN"]), top_k=5)
        assert {h.chunk_id for h in hits} == {"plain", "nf"}  # nf_oc needs ORCON too

    def test_program_marked_chunks_denied_by_default(self):
        store = InMemoryVectorStore()
        store.upsert(
            [
                record("open", "program report", "S"),
                record("sap", "program report", "S", program="ALPHA"),
            ]
        )
        hits = store.search(query("program report"), flt(["S"]), top_k=5)
        assert {h.chunk_id for h in hits} == {"open"}
        hits = store.search(query("program report"), flt(["S"], programs=["ALPHA"]), top_k=5)
        assert {h.chunk_id for h in hits} == {"open", "sap"}

    def test_search_without_filter_rejected(self):
        store = InMemoryVectorStore()
        store.upsert([record("u1", "text", "U")])
        with pytest.raises(MarkingError):
            store.search(query("text"), None, top_k=1)

    def test_hits_carry_full_marking_metadata(self):
        store = InMemoryVectorStore()
        store.upsert([record("s1", "marked text", "S", ["NOFORN"])])
        (hit,) = store.search(
            query("marked text"), flt(["S"], controls=["NOFORN"]), top_k=1
        )
        assert hit.classification == "S"
        assert hit.portion_marking == "(S)"
        assert hit.dissem_controls == ["NOFORN"]
        assert hit.content_hash == "x" * 64


class TestLevelsUpTo:
    def test_ceiling_expansion(self):
        assert levels_up_to(ClassificationLevel.S) == [
            ClassificationLevel.U,
            ClassificationLevel.C,
            ClassificationLevel.S,
        ]
        assert levels_up_to(ClassificationLevel.U) == [ClassificationLevel.U]
