"""Live PostgreSQL + pgvector tests, run as the least-privilege service role.

Skipped unless both URLs are set, e.g.:
  RAGMT_TEST_PG_APP_URL=postgresql+psycopg2://ragmt_app:...@127.0.0.1:54329/ragmt
  RAGMT_TEST_PG_OWNER_URL=postgresql+psycopg2://ragmt_owner:...@127.0.0.1:54329/ragmt
The database must have migrations 001-004 and installer/common/roles.sql
applied, exactly as the installers do. Tables are truncated before each test.
"""

import os
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

APP_URL = os.environ.get("RAGMT_TEST_PG_APP_URL")
OWNER_URL = os.environ.get("RAGMT_TEST_PG_OWNER_URL")
pytestmark = pytest.mark.skipif(not (APP_URL and OWNER_URL), reason="live Postgres not configured")

PW = "Correct-Horse-Battery-9"
TABLES = ("governance_events, product_sources, product_claims, products, model_endpoints, "
          "auth_sessions, users, policy_versions, query_audit_log, chunks, sections, documents")


@pytest.fixture()
def pg(monkeypatch):
    from backend.api.users import UserIn, create_user
    from backend.db.database import get_session
    from backend.embedding.embedder import HashingEmbedder, get_embedder
    from backend.main import app
    from backend.policy import store as policy_store
    from backend.retrieval.vector_store import PgVectorStore, get_vector_store

    monkeypatch.setenv("RAGMT_AUTH_MODE", "production")
    monkeypatch.setenv("RAGMT_DEV", "1")
    owner = create_engine(OWNER_URL)
    with owner.begin() as c:
        c.execute(text("TRUNCATE " + TABLES + " RESTART IDENTITY CASCADE"))
    engine = create_engine(APP_URL)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    store = PgVectorStore(engine, dim=384)
    emb = HashingEmbedder(dim=384)

    def override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = override
    app.dependency_overrides[get_embedder] = lambda: emb
    app.dependency_overrides[get_vector_store] = lambda: store
    db = Session()
    pol = policy_store.current(db)
    policy_store.update(db, actor="setup", settings=dict(pol.settings, system_high="TS"),
                        justification="live postgres test installation at TOP SECRET")
    for name, roles, clr in [("admin1", ["admin"], "TS"), ("ao1", ["ao"], "TS"),
                             ("author1", ["author"], "TS"), ("rev1", ["reviewer"], "TS"),
                             ("rel1", ["releaser"], "TS"), ("aud1", ["auditor"], "TS"),
                             ("low", ["author"], "U")]:
        create_user(db, UserIn(username=name, display_name=name.upper(), initial_password=PW,
                               roles=roles, clearance=clr, citizenship="USA"), actor="setup")
    db.commit()
    db.close()
    with TestClient(app) as c:
        yield c, engine, owner, Session
    app.dependency_overrides.clear()
    engine.dispose()
    owner.dispose()


def login(c, u):
    r = c.post("/auth/login", json={"username": u, "password": PW})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def seed(c):
    h = login(c, "author1")
    r = c.post("/ingest/documents", headers=h, json={
        "title": "Harbor Report", "source_system": "test", "classification": "S",
        "dissem_controls": [], "sections": [
            {"content": "Vessel Alpha docked at pier four on Monday.", "portion_marking": "(U)"},
            {"content": "Vessel Alpha manifest lists industrial pumps.", "portion_marking": "(S//NF)"},
            {"content": "Vessel Alpha crew rotation is shared with partners.",
             "portion_marking": "(S//REL TO USA, GBR)"}]})
    assert r.status_code == 201, r.text
    r = c.post("/ingest/documents/{}/embed".format(r.json()["id"]), headers=h)
    assert r.status_code == 200, r.text
    a = login(c, "admin1")
    ep = c.post("/models", headers=a, json={"name": "dev", "adapter": "dev_extractive",
                "base_url": "local://dev", "model_id": "dev", "max_classification": "S"}).json()
    c.patch("/models/" + ep["id"], headers=a, json={"enabled": True})
    return ep["id"]


def test_pgvector_filtering_in_sql(pg):
    c, *_ = pg
    seed(c)
    hits = c.post("/query", headers=login(c, "low"), json={"query": "Vessel Alpha"}).json()["hits"]
    assert hits and {h["classification"] for h in hits} == {"U"}
    hits = c.post("/query", headers=login(c, "author1"), json={"query": "Vessel Alpha"}).json()["hits"]
    assert len(hits) == 3


def test_full_release_workflow_on_postgres(pg):
    c, engine, owner, Session = pg
    ep = seed(c)
    au = login(c, "author1")
    p = c.post("/products", headers=au, json={"title": "Vessel Alpha", "question": "Vessel Alpha",
               "model_endpoint_id": ep}).json()
    assert p["banner"] is not None
    for cl in p["claims"]:
        if cl["kind"] == "uncited":
            c.patch("/products/{}/claims/{}".format(p["id"], cl["id"]), headers=au,
                    json={"portion_marking": "(U)"})
            c.patch("/products/{}/claims/{}".format(p["id"], cl["id"]), headers=au,
                    json={"kind": "judgment"})
    r = c.post("/products/{}/submit".format(p["id"]), headers=au)
    assert r.status_code == 200, r.text
    assert r.json()["banner"] == "SECRET//NOFORN"
    rv = login(c, "rev1")
    full = c.get("/products/" + p["id"], headers=rv).json()
    for cl in full["claims"]:
        if cl["needs_disposition"]:
            c.post("/products/{}/claims/{}/disposition".format(p["id"], cl["id"]), headers=rv,
                   json={"disposition": "accept_judgment"})
    assert c.post("/products/{}/approve".format(p["id"]), headers=rv).json()["state"] == "approved"
    assert c.post("/products/{}/release".format(p["id"]),
                  headers=login(c, "rel1")).json()["state"] == "released"
    v = c.get("/governance/verify", headers=login(c, "aud1")).json()
    assert v["intact"] and v["events_checked"] > 15


def test_service_role_cannot_rewrite_history(pg):
    c, engine, owner, _ = pg
    seed(c)
    for stmt in ("UPDATE governance_events SET actor = 'x'", "DELETE FROM governance_events",
                 "UPDATE query_audit_log SET user_id = 'x'", "DELETE FROM query_audit_log",
                 "DELETE FROM policy_versions", "DROP TRIGGER trg_governance_immutable ON governance_events",
                 "CREATE TABLE sneaky (id int)"):
        with pytest.raises(DBAPIError) as ei:
            with engine.begin() as conn:
                conn.execute(text(stmt))
        assert "permission denied" in str(ei.value) or "must be owner" in str(ei.value), stmt


def test_trigger_blocks_owner_rewrites(pg):
    c, engine, owner, _ = pg
    seed(c)
    with pytest.raises(DBAPIError, match="append-only"):
        with owner.begin() as conn:
            conn.execute(text("UPDATE governance_events SET actor = 'x'"))


def test_separation_of_duties_check_constraint(pg):
    c, engine, owner, _ = pg
    ep = seed(c)
    p = c.post("/products", headers=login(c, "author1"), json={
        "title": "t", "question": "Vessel Alpha", "model_endpoint_id": ep}).json()
    with pytest.raises(DBAPIError, match="check constraint"):
        with engine.begin() as conn:
            conn.execute(text("UPDATE products SET reviewer_id = author_id WHERE id = :i"),
                         {"i": p["id"]})


def test_hash_chain_under_concurrent_writers(pg):
    from backend.governance import chain
    c, engine, owner, Session = pg
    errors = []

    def writer(n):
        s = Session()
        try:
            for i in range(25):
                chain.record(s, actor="t{}".format(n), event_type="test.concurrent",
                             subject_type="test", subject_id="{}-{}".format(n, i), payload={})
                s.commit()
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)
        finally:
            s.close()

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    s = Session()
    ok, bad, n = chain.verify(s)
    s.close()
    assert ok, "chain forked at seq {}".format(bad)
    assert n >= 150
