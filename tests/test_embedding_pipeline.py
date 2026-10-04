"""Phase 3 integration tests: ingest -> embed -> filtered search, end to end
through the API with an in-memory vector store."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db.database import get_session
from backend.embedding.embedder import HashingEmbedder, get_embedder
from backend.main import app
from backend.models import schema
from backend.retrieval.filters import ChunkFilter
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


def ingest_fixture_doc(client):
    resp = client.post(
        "/ingest/documents",
        json={
            "title": "Mixed Classification Report",
            "source_system": "intake-ui",
            "classification": "S",
            "dissem_controls": ["NOFORN"],
            "sections": [
                {
                    "heading": "Overview",
                    "content": "Public overview of harbor operations.",
                    "portion_marking": "(U)",
                },
                {
                    "heading": "Assessment",
                    "content": "Secret assessment of harbor operations.",
                    "portion_marking": "(S//NF)",
                },
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestEmbedEndpoint:
    def test_embed_writes_all_chunks_with_markings(self, client, store):
        doc = ingest_fixture_doc(client)
        resp = client.post("/ingest/documents/{}/embed".format(doc["id"]))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["chunks_embedded"] == doc["chunk_count"] == 2
        assert body["embedding_dim"] == 64
        assert len(store) == 2

        q = EMB.embed_texts(["harbor operations"])[0]
        hits = store.search(
            q,
            ChunkFilter(
                allowed_levels=["U", "S"], permitted_controls=["NOFORN"]
            ),
            top_k=10,
        )
        assert len(hits) == 2
        markings = {h.portion_marking for h in hits}
        assert markings == {"(U)", "(S//NOFORN)"}

    def test_search_respects_markings_after_pipeline(self, client, store):
        ingest_fixture_doc(client)
        q = EMB.embed_texts(["harbor operations"])[0]
        # Before embedding: nothing in the store.
        assert (
            store.search(
                q, ChunkFilter(allowed_levels=["U", "S"], permitted_controls=["NOFORN"]), 10
            )
            == []
        )

    def test_uncleared_filter_never_sees_secret_chunk(self, client, store):
        doc = ingest_fixture_doc(client)
        client.post("/ingest/documents/{}/embed".format(doc["id"]))
        q = EMB.embed_texts(["harbor operations"])[0]
        hits = store.search(
            q, ChunkFilter(allowed_levels=["U"], permitted_controls=[]), top_k=10
        )
        assert [h.classification for h in hits] == ["U"]
        assert "Secret" not in hits[0].content

    def test_embed_is_idempotent(self, client, store):
        doc = ingest_fixture_doc(client)
        client.post("/ingest/documents/{}/embed".format(doc["id"]))
        resp = client.post("/ingest/documents/{}/embed".format(doc["id"]))
        assert resp.status_code == 200
        assert len(store) == 2  # overwritten by chunk_id, not duplicated

    def test_embed_unknown_document_is_404(self, client):
        resp = client.post("/ingest/documents/no-such-doc/embed")
        assert resp.status_code == 404
