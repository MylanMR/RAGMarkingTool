"""Integration tests for the intake API (Phase 1) against in-memory sqlite.

Verifies the no-silent-defaults contract end to end: unmarked sections are
rejected with 422 and nothing is persisted.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db.database import get_session
from backend.main import app
from backend.models import schema


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
def client(db_session):
    def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def valid_payload():
    return {
        "title": "Quarterly Threat Assessment",
        "source_system": "intake-ui",
        "classification": "S",
        "dissem_controls": ["NOFORN"],
        "sections": [
            {"heading": "Overview", "content": "Unclassified overview.", "portion_marking": "(U)"},
            {"heading": "Findings", "content": "Secret findings.", "portion_marking": "(S//NF)"},
        ],
    }


class TestIngestHappyPath:
    def test_ingest_persists_documents_sections_chunks(self, client, db_session):
        resp = client.post("/ingest/documents", json=valid_payload())
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["classification"] == "S"
        assert body["section_count"] == 2
        assert body["chunk_count"] == 2

        assert db_session.query(schema.Document).count() == 1
        assert db_session.query(schema.Section).count() == 2
        chunks = db_session.query(schema.Chunk).order_by(schema.Chunk.seq).all()
        assert [c.classification for c in chunks] == ["U", "S"]
        assert chunks[1].dissem_controls == ["NOFORN"]
        assert chunks[1].portion_marking == "(S//NOFORN)"

    def test_banner_may_dominate_sections(self, client):
        payload = valid_payload()
        payload["classification"] = "TS"
        resp = client.post("/ingest/documents", json=payload)
        assert resp.status_code == 201

    def test_ts_sci_level_and_ic_caveats(self, client, db_session):
        payload = valid_payload()
        payload["classification"] = "TS/SCI"
        payload["sections"].append(
            {
                "heading": "Compartmented",
                "content": "SCI-level propin detail.",
                "portion_marking": "(TS/SCI//PROPIN)",
            }
        )
        resp = client.post("/ingest/documents", json=payload)
        assert resp.status_code == 201, resp.text
        chunks = db_session.query(schema.Chunk).order_by(schema.Chunk.seq).all()
        assert chunks[-1].classification == "TS/SCI"
        assert chunks[-1].portion_marking == "(TS/SCI//PROPIN)"
        assert chunks[-1].dissem_controls == ["PROPIN"]


class TestIngestRejection:
    def test_section_without_marking_is_422(self, client, db_session):
        payload = valid_payload()
        del payload["sections"][1]["portion_marking"]
        resp = client.post("/ingest/documents", json=payload)
        assert resp.status_code == 422
        assert db_session.query(schema.Document).count() == 0
        assert db_session.query(schema.Chunk).count() == 0

    def test_document_without_banner_is_422(self, client):
        payload = valid_payload()
        del payload["classification"]
        assert client.post("/ingest/documents", json=payload).status_code == 422

    def test_banner_below_section_level_is_422(self, client, db_session):
        payload = valid_payload()
        payload["classification"] = "C"  # sections go up to S
        resp = client.post("/ingest/documents", json=payload)
        assert resp.status_code == 422
        assert "dominate" in resp.json()["detail"]
        assert db_session.query(schema.Document).count() == 0

    def test_malformed_portion_marking_is_422(self, client, db_session):
        payload = valid_payload()
        payload["sections"][0]["portion_marking"] = "(S//BANANA)"
        resp = client.post("/ingest/documents", json=payload)
        assert resp.status_code == 422
        assert db_session.query(schema.Chunk).count() == 0

    def test_empty_sections_list_is_422(self, client):
        payload = valid_payload()
        payload["sections"] = []
        assert client.post("/ingest/documents", json=payload).status_code == 422

    def test_blank_section_content_is_422(self, client):
        payload = valid_payload()
        payload["sections"][0]["content"] = "   "
        assert client.post("/ingest/documents", json=payload).status_code == 422

    def test_conflicting_dissem_controls_is_422(self, client):
        payload = valid_payload()
        payload["dissem_controls"] = ["NOFORN", "REL TO USA, GBR"]
        assert client.post("/ingest/documents", json=payload).status_code == 422
