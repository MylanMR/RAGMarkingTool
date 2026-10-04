"""Phase 4 integration tests: ingest -> embed -> PDP-filtered query through
the API, simulating users with partial access against a mixed-classification
document set (the spec's Phase 6 integration scenario).
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db.database import get_session
from backend.embedding.embedder import HashingEmbedder, get_embedder
from backend.main import app
from backend.models import schema
from backend.retrieval.filtered_search import RetrievalIntegrityError, filtered_search
from backend.retrieval.pdp import UserAttributes
from backend.retrieval.vector_store import InMemoryVectorStore, get_vector_store

EMB = HashingEmbedder(dim=64)


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    schema.Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSession()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def store():
    return InMemoryVectorStore(dim=64)


@pytest.fixture()
def client(db_session, store):
    def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_embedder] = lambda: EMB
    app.dependency_overrides[get_vector_store] = lambda: store
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def corpus(client):
    """Mixed-classification corpus, every section about 'harbor operations'
    so similarity alone would surface all of them."""
    docs = [
        {
            "title": "Mixed Report",
            "source_system": "test",
            "classification": "TS",
            "dissem_controls": [],
            "sections": [
                {"content": "Public harbor operations overview.", "portion_marking": "(U)"},
                {"content": "Confidential harbor operations note.", "portion_marking": "(C)"},
                {"content": "Secret harbor operations noforn detail.", "portion_marking": "(S//NF)"},
                {"content": "Secret harbor operations shared with allies.", "portion_marking": "(S//REL TO USA, GBR)"},
                {"content": "Top secret harbor operations assessment.", "portion_marking": "(TS)"},
            ],
        },
        {
            "title": "Program Report",
            "source_system": "test",
            "classification": "S",
            "dissem_controls": [],
            "program": "ALPHA",
            "sections": [
                {"content": "Program harbor operations findings.", "portion_marking": "(S)"},
            ],
        },
    ]
    for doc in docs:
        resp = client.post("/ingest/documents", json=doc)
        assert resp.status_code == 201, resp.text
        doc_id = resp.json()["id"]
        assert client.post("/ingest/documents/{}/embed".format(doc_id)).status_code == 200


def run_query(client, clearance, citizenship, compartments=(), ntk=(), user_id="tester"):
    resp = client.post(
        "/query",
        json={
            "query": "harbor operations",
            "top_k": 20,
            "user": {
                "user_id": user_id,
                "clearance": clearance,
                "citizenship": citizenship,
                "compartments": list(compartments),
                "need_to_know_groups": list(ntk),
            },
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestPartialAccessQueries:
    def test_uncleared_us_user_sees_only_u(self, client, corpus):
        body = run_query(client, "U", "USA")
        assert {h["portion_marking"] for h in body["hits"]} == {"(U)"}

    def test_secret_us_user(self, client, corpus):
        body = run_query(client, "S", "USA")
        assert {h["portion_marking"] for h in body["hits"]} == {
            "(U)", "(C)", "(S//NOFORN)", "(S//REL TO USA, GBR)"
        }

    def test_secret_uk_user_no_noforn_no_program(self, client, corpus):
        body = run_query(client, "S", "GBR")
        markings = {h["portion_marking"] for h in body["hits"]}
        assert markings == {"(U)", "(C)", "(S//REL TO USA, GBR)"}
        assert all("noforn" not in h["content"].lower() for h in body["hits"])

    def test_french_liaison_gets_no_rel_or_noforn(self, client, corpus):
        body = run_query(client, "S", "FRA")
        assert {h["portion_marking"] for h in body["hits"]} == {"(U)", "(C)"}

    def test_ts_user_without_compartment_misses_program_chunk(self, client, corpus):
        body = run_query(client, "TS", "USA")
        assert {h["portion_marking"] for h in body["hits"]} == {
            "(U)", "(C)", "(S//NOFORN)", "(S//REL TO USA, GBR)", "(TS)"
        }
        assert all(h["program"] is None for h in body["hits"])

    def test_compartmented_user_gets_program_chunk(self, client, corpus):
        body = run_query(client, "TS", "USA", compartments=["ALPHA"])
        programs = {h["program"] for h in body["hits"]}
        assert programs == {None, "ALPHA"}

    def test_every_decision_logged_with_reason(self, client, corpus):
        body = run_query(client, "S", "GBR")
        assert len(body["decisions"]) == len(body["hits"])
        assert all(d["reason"] for d in body["decisions"])
        assert body["filter_summary"]["allowed_levels"] == ["U", "C", "S"]

    def test_invalid_user_attributes_422(self, client, corpus):
        resp = client.post(
            "/query",
            json={
                "query": "harbor operations",
                "user": {"user_id": "x", "clearance": "SECRET", "citizenship": "USA"},
            },
        )
        assert resp.status_code == 422


class TestIntegrityFailClosed:
    def test_store_pdp_divergence_raises(self, store):
        """If the store ever returns a chunk the PDP denies, the search fails
        closed instead of returning partial results."""
        from backend.retrieval.vector_store import SearchHit

        class BrokenStore:
            dim = 64

            def distinct_controls(self):
                return []

            def search(self, q, flt, top_k):
                return [
                    SearchHit(
                        chunk_id="leak",
                        parent_doc_id="doc-x",
                        content="ts content",
                        score=1.0,
                        classification="TS",
                        portion_marking="(TS)",
                        dissem_controls=[],
                        program=None,
                        content_hash="x" * 64,
                    )
                ]

        u = UserAttributes(user_id="u1", clearance="U", citizenship="USA")
        with pytest.raises(RetrievalIntegrityError):
            filtered_search(u, "anything", EMB, BrokenStore(), top_k=5)
