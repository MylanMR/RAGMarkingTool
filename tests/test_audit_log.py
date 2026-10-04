"""Phase 5 tests: every query attempt is audited with full decision context,
and the log is queryable through the audit API."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db.database import get_session
from backend.embedding.embedder import HashingEmbedder, get_embedder
from backend.main import app
from backend.models import schema
from backend.retrieval.vector_store import InMemoryVectorStore, SearchHit, get_vector_store

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
    resp = client.post(
        "/ingest/documents",
        json={
            "title": "Mixed Report",
            "source_system": "test",
            "classification": "S",
            "dissem_controls": [],
            "sections": [
                {"content": "Public harbor operations overview.", "portion_marking": "(U)"},
                {"content": "Secret harbor operations detail.", "portion_marking": "(S//NF)"},
            ],
        },
    )
    assert resp.status_code == 201
    doc_id = resp.json()["id"]
    assert client.post("/ingest/documents/{}/embed".format(doc_id)).status_code == 200
    return doc_id


def query_payload(user_id="analyst", clearance="S", citizenship="USA"):
    return {
        "query": "harbor operations",
        "top_k": 10,
        "user": {"user_id": user_id, "clearance": clearance, "citizenship": citizenship},
    }


class TestAuditRecording:
    def test_successful_query_fully_audited(self, client, corpus):
        resp = client.post("/query", json=query_payload())
        assert resp.status_code == 200
        audit_id = resp.json()["audit_id"]

        entry = client.get("/audit/queries/{}".format(audit_id)).json()
        assert entry["outcome"] == "ok"
        assert entry["user_id"] == "analyst"
        assert entry["clearance"] == "S"
        assert entry["citizenship"] == "USA"
        assert entry["query_text"] == "harbor operations"
        assert entry["result_count"] == 2
        assert entry["ts"]
        # Attributes evaluated, markings returned, and PDP reasons all present.
        assert entry["user_attributes"]["clearance"] == "S"
        assert entry["filter_summary"]["allowed_levels"] == ["U", "C", "S"]
        markings = {c["portion_marking"] for c in entry["returned_chunks"]}
        assert markings == {"(U)", "(S//NOFORN)"}
        assert len(entry["decisions"]) == 2
        assert all(d["reason"] for d in entry["decisions"])

    def test_every_query_gets_a_row(self, client, corpus, db_session):
        for _ in range(3):
            assert client.post("/query", json=query_payload()).status_code == 200
        assert db_session.query(schema.QueryAuditLog).count() == 3

    def test_rejected_attributes_still_audited(self, client, corpus, db_session):
        resp = client.post(
            "/query", json=query_payload(clearance="SECRET")  # invalid level
        )
        assert resp.status_code == 422
        row = db_session.query(schema.QueryAuditLog).one()
        assert row.outcome == "rejected_attributes"
        assert row.result_count == 0
        assert row.clearance is None
        assert "SECRET" in row.detail
        assert row.user_attributes["clearance"] == "SECRET"

    def test_integrity_failure_audited_and_500(self, client, corpus, db_session, store):
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

        app.dependency_overrides[get_vector_store] = lambda: BrokenStore()
        resp = client.post("/query", json=query_payload(clearance="U"))
        assert resp.status_code == 500
        row = (
            db_session.query(schema.QueryAuditLog)
            .filter(schema.QueryAuditLog.outcome == "integrity_failure")
            .one()
        )
        assert "leak" in row.detail
        assert row.clearance == "U"


class TestAuditQueryability:
    @pytest.fixture()
    def populated(self, client, corpus):
        client.post("/query", json=query_payload(user_id="alice"))
        client.post("/query", json=query_payload(user_id="bob"))
        client.post("/query", json=query_payload(user_id="alice"))
        client.post("/query", json=query_payload(user_id="mallory", clearance="SECRET"))

    def test_filter_by_user(self, client, populated):
        body = client.get("/audit/queries", params={"user_id": "alice"}).json()
        assert body["total"] == 2
        assert all(e["user_id"] == "alice" for e in body["entries"])

    def test_filter_by_outcome(self, client, populated):
        body = client.get("/audit/queries", params={"outcome": "rejected_attributes"}).json()
        assert body["total"] == 1
        assert body["entries"][0]["user_id"] == "mallory"

    def test_unknown_outcome_param_rejected(self, client, populated):
        assert client.get("/audit/queries", params={"outcome": "nope"}).status_code == 422

    def test_pagination_and_ordering(self, client, populated):
        page = client.get("/audit/queries", params={"limit": 2}).json()
        assert page["total"] == 4
        assert len(page["entries"]) == 2
        rest = client.get("/audit/queries", params={"limit": 10, "offset": 2}).json()
        assert len(rest["entries"]) == 2
        all_ids = {e["id"] for e in page["entries"]} | {e["id"] for e in rest["entries"]}
        assert len(all_ids) == 4

    def test_time_window_filter(self, client, populated):
        body = client.get(
            "/audit/queries", params={"since": "2000-01-01T00:00:00"}
        ).json()
        assert body["total"] == 4
        body = client.get(
            "/audit/queries", params={"until": "2000-01-01T00:00:00"}
        ).json()
        assert body["total"] == 0

    def test_get_unknown_entry_404(self, client, populated):
        assert client.get("/audit/queries/no-such-id").status_code == 404
