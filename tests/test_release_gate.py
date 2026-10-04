"""Phase 7-10: authenticated production mode, AO policy, model egress and
ceilings, claim/citation enforcement, and the release gate end to end."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.users import UserIn, create_user
from backend.db.database import get_session
from backend.embedding.embedder import HashingEmbedder, get_embedder
from backend.governance import chain
from backend.llm import adapters
from backend.main import app
from backend.models import schema
from backend.models.governance import GovernanceEvent, ModelEndpoint
from backend.policy import catalog, store as policy_store
from backend.retrieval.vector_store import InMemoryVectorStore, get_vector_store

PW = "Correct-Horse-Battery-9"
EMB = HashingEmbedder(dim=64)


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("RAGMT_AUTH_MODE", "production")
    monkeypatch.setenv("RAGMT_DEV", "1")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    schema.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    store = InMemoryVectorStore(dim=64)

    def override():
        yield db

    app.dependency_overrides[get_session] = override
    app.dependency_overrides[get_embedder] = lambda: EMB
    app.dependency_overrides[get_vector_store] = lambda: store
    pol = policy_store.current(db)
    policy_store.update(db, actor="setup", settings=dict(pol.settings, system_high="TS"),
                        justification="test installation accredited to TOP SECRET")
    for name, roles, clr in [("admin1", ["admin"], "TS"), ("ao1", ["ao"], "TS"),
                             ("author1", ["author"], "TS"), ("rev1", ["reviewer"], "TS"),
                             ("rel1", ["releaser"], "TS"), ("aud1", ["auditor"], "TS"),
                             ("lowuser", ["author", "reviewer"], "C")]:
        create_user(db, UserIn(username=name, display_name=name.upper(), initial_password=PW,
                               roles=roles, clearance=clr, citizenship="USA"), actor="setup")
    db.commit()
    with TestClient(app) as c:
        yield c, db
    app.dependency_overrides.clear()
    adapters.transport_override = None
    db.close()
    engine.dispose()


def login(c, user):
    r = c.post("/auth/login", json={"username": user, "password": PW})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def ingest(c, h):
    doc = {"title": "Harbor Report", "source_system": "test", "classification": "S",
           "dissem_controls": [], "sections": [
               {"content": "Vessel Alpha docked at pier four on Monday.", "portion_marking": "(U)"},
               {"content": "Vessel Alpha manifest lists industrial pumps.", "portion_marking": "(S//NF)"},
           ]}
    r = c.post("/ingest/documents", json=doc, headers=h)
    assert r.status_code == 201, r.text
    assert c.post("/ingest/documents/{}/embed".format(r.json()["id"]), headers=h).status_code == 200


def dev_endpoint(c, ceiling="S"):
    a = login(c, "admin1")
    r = c.post("/models", headers=a, json={"name": "dev", "adapter": "dev_extractive",
               "base_url": "local://dev", "model_id": "dev", "max_classification": ceiling})
    assert r.status_code == 201, r.text
    ep = r.json()
    assert ep["enabled"] is False           # endpoints are created disabled
    c.patch("/models/" + ep["id"], headers=a, json={"enabled": True})
    return ep["id"]


def draft(c, h, ep_id):
    r = c.post("/products", headers=h, json={"title": "Vessel Alpha", "question":
               "What is known about Vessel Alpha?", "model_endpoint_id": ep_id})
    assert r.status_code == 201, r.text
    return r.json()


# --- production auth ------------------------------------------------------

def test_body_attributes_rejected_without_session(env):
    c, _ = env
    r = c.post("/query", json={"query": "x", "user": {"user_id": "a", "clearance": "TS",
                                                      "citizenship": "USA"}})
    assert r.status_code == 401


def test_bad_password_generic_and_lockout(env):
    c, db = env
    for _ in range(3):
        r = c.post("/auth/login", json={"username": "author1", "password": "wrong-Password-1"})
        assert r.status_code == 401
    r = c.post("/auth/login", json={"username": "author1", "password": PW})
    assert r.status_code == 423
    r = c.post("/auth/login", json={"username": "nobody", "password": PW})
    assert r.status_code == 401 and r.json()["detail"] == "invalid username or password"


def test_query_uses_session_attributes_not_body(env):
    c, _ = env
    ingest(c, login(c, "author1"))
    h = login(c, "lowuser")
    r = c.post("/query", headers=h, json={"query": "Vessel Alpha", "user": {
        "user_id": "spoof", "clearance": "TS", "citizenship": "USA"}})
    assert r.status_code == 200
    assert r.json()["user_id"] == "lowuser"
    assert all(hit["classification"] in ("U", "C") for hit in r.json()["hits"])


def test_ingest_above_clearance_refused(env):
    c, _ = env
    r = c.post("/ingest/documents", headers=login(c, "lowuser"), json={
        "title": "x", "source_system": "t", "classification": "S", "dissem_controls": [],
        "sections": [{"content": "secret", "portion_marking": "(S)"}]})
    assert r.status_code == 403


def test_admin_and_ao_separation(env):
    c, _ = env
    r = c.post("/users", headers=login(c, "admin1"), json={
        "username": "both", "display_name": "Both", "initial_password": PW,
        "roles": ["admin", "ao"], "clearance": "S", "citizenship": "USA"})
    assert r.status_code == 422


# --- policy ---------------------------------------------------------------

def test_policy_relaxation_requires_justification_and_ao(env):
    c, _ = env
    cur = c.get("/policy", headers=login(c, "author1")).json()
    new = json.loads(json.dumps(cur["settings"]))
    new["citation_enforcement"]["S"] = "advisory"
    assert c.put("/policy", headers=login(c, "admin1"), json={"settings": new}).status_code == 403
    ao = login(c, "ao1")
    r = c.put("/policy", headers=ao, json={"settings": new, "justification": "short"})
    assert r.status_code == 422 and "justification" in r.json()["detail"]
    r = c.put("/policy", headers=ao, json={"settings": new, "justification":
              "Exercise environment with synthetic data only, approved 4 Oct 2026"})
    assert r.status_code == 200
    hist = c.get("/policy/history", headers=ao).json()
    assert hist[0]["relaxed"] == ["citation_enforcement[S]"]


def test_policy_rejects_missing_levels():
    s = catalog.defaults()
    del s["review_rule"]["TS"]
    with pytest.raises(catalog.PolicyError):
        catalog.validate(s)


# --- model egress and ceilings -------------------------------------------

def test_cloud_endpoint_refused_under_local_only_then_needs_ao(env, monkeypatch):
    c, db = env
    ingest(c, login(c, "author1"))
    a = login(c, "admin1")
    monkeypatch.setenv("TEST_KEY", "sk-test")
    ep = c.post("/models", headers=a, json={"name": "cloud", "adapter": "openai_compatible",
                "base_url": "https://api.example.com/v1", "model_id": "gpt-x",
                "max_classification": "U", "credential_ref": "env:TEST_KEY"}).json()
    c.patch("/models/" + ep["id"], headers=a, json={"enabled": True})
    h = login(c, "author1")
    body = {"title": "t", "question": "Vessel Alpha", "model_endpoint_id": ep["id"]}
    r = c.post("/products", headers=h, json=body)
    assert r.status_code == 403 and "local-only" in r.json()["detail"]
    ao = login(c, "ao1")
    s = c.get("/policy", headers=ao).json()["settings"]
    c.put("/policy", headers=ao, json={"settings": dict(s, egress_mode="allowlist"),
          "justification": "Classified cloud region approved under ATO addendum 3"})
    r = c.post("/products", headers=h, json=body)
    assert r.status_code == 403 and "approved by an AO" in r.json()["detail"]
    assert c.post("/models/{}/approve".format(ep["id"]), headers=ao).status_code == 200

    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"model": "gpt-x-2026", "choices": [{"message": {
            "content": "Vessel Alpha docked at pier four. [S1] It carried weapons. [S9]"}}]})

    adapters.transport_override = httpx.MockTransport(handler)
    r = c.post("/products", headers=h, json=body)
    assert r.status_code == 201, r.text
    p = r.json()
    # U ceiling: the S//NF chunk was withheld from the cloud model
    assert "pumps" not in seen["body"]["messages"][1]["content"]
    assert p["disclosure"]["withheld_count"] == 1
    assert p["disclosure"]["model_reported"] == "gpt-x-2026"
    assert seen["auth"] == "Bearer sk-test"
    fabricated = [cl for cl in p["claims"] if cl["invalid_refs"]]
    assert fabricated and fabricated[0]["kind"] == "uncited"


def test_editing_endpoint_url_clears_approval(env):
    c, db = env
    a = login(c, "admin1")
    ep = c.post("/models", headers=a, json={"name": "m", "adapter": "openai_compatible",
                "base_url": "https://llm.internal/v1", "model_id": "x",
                "max_classification": "S"}).json()
    c.post("/models/{}/approve".format(ep["id"]), headers=login(c, "ao1"))
    r = c.patch("/models/" + ep["id"], headers=a, json={"base_url": "https://other/v1"})
    assert r.json()["approved_by"] is None and r.json()["enabled"] is False


def test_secrets_never_stored(env):
    c, _ = env
    r = c.post("/models", headers=login(c, "admin1"), json={"name": "k",
               "adapter": "openai_compatible", "base_url": "http://127.0.0.1:11434/v1",
               "model_id": "llama", "max_classification": "S", "credential_ref": "sk-raw-key"})
    assert r.status_code == 422


def test_plain_http_refused_off_loopback(env, monkeypatch):
    c, db = env
    monkeypatch.setenv("RAGMT_ENCLAVE_CIDRS", "10.0.0.0/8")
    a = login(c, "admin1")
    ep = c.post("/models", headers=a, json={"name": "lan", "adapter": "openai_compatible",
                "base_url": "http://10.1.2.3:8000/v1", "model_id": "x",
                "max_classification": "S"}).json()
    c.patch("/models/" + ep["id"], headers=a, json={"enabled": True})
    ingest(c, login(c, "author1"))
    r = c.post("/products", headers=login(c, "author1"), json={"title": "t",
               "question": "Vessel Alpha", "model_endpoint_id": ep["id"]})
    assert r.status_code == 403 and "HTTPS" in r.json()["detail"]


# --- release gate ---------------------------------------------------------

def test_block_mode_then_two_person_release(env):
    c, db = env
    au = login(c, "author1")
    ingest(c, au)
    p = draft(c, au, dev_endpoint(c))
    uncited = [cl for cl in p["claims"] if cl["kind"] == "uncited"]
    assert uncited and uncited[0]["portion_marking"] is None    # no silent default
    r = c.post("/products/{}/submit".format(p["id"]), headers=au)
    assert r.status_code == 422 and "portion marking" in r.json()["detail"]
    cid = uncited[0]["id"]
    c.patch("/products/{}/claims/{}".format(p["id"], cid), headers=au,
            json={"portion_marking": "(U)"})
    r = c.post("/products/{}/submit".format(p["id"]), headers=au)
    assert r.status_code == 422 and "blocks uncited" in r.json()["detail"]   # S -> block
    c.patch("/products/{}/claims/{}".format(p["id"], cid), headers=au, json={"kind": "judgment"})
    r = c.post("/products/{}/submit".format(p["id"]), headers=au)
    assert r.status_code == 200 and r.json()["review_rule"] == "two_person"
    assert r.json()["banner"] == "SECRET//NOFORN"

    assert c.post("/products/{}/approve".format(p["id"]), headers=au).status_code == 403
    rv = login(c, "rev1")
    r = c.post("/products/{}/approve".format(p["id"]), headers=rv)
    assert r.status_code == 422 and "disposition" in r.json()["detail"]
    c.post("/products/{}/claims/{}/disposition".format(p["id"], cid), headers=rv,
           json={"disposition": "accept_judgment", "note": "Reasonable inference"})
    r = c.post("/products/{}/approve".format(p["id"]), headers=rv)
    assert r.json()["state"] == "approved"
    assert c.post("/products/{}/release".format(p["id"]), headers=rv).status_code == 403
    r = c.post("/products/{}/release".format(p["id"]), headers=login(c, "rel1"))
    assert r.json()["state"] == "released"
    md = c.get("/products/{}/export".format(p["id"]), headers=au).text
    assert md.startswith("SECRET//NOFORN") and "AI-assistance disclosure" in md
    assert "NOT RELEASED" not in md and "(Analytic judgment)" in md


def test_low_clearance_cannot_see_secret_product(env):
    c, _ = env
    au = login(c, "author1")
    ingest(c, au)
    p = draft(c, au, dev_endpoint(c))
    assert c.get("/products/" + p["id"], headers=login(c, "lowuser")).status_code == 404


def test_cited_marking_cannot_go_below_sources(env):
    c, _ = env
    au = login(c, "author1")
    ingest(c, au)
    p = draft(c, au, dev_endpoint(c))
    sec = next(cl for cl in p["claims"] if cl["derived_marking"] == "(S//NOFORN)")
    r = c.patch("/products/{}/claims/{}".format(p["id"], sec["id"]), headers=au,
                json={"portion_marking": "(U)"})
    assert r.status_code == 422 and "below" in r.json()["detail"]


def test_single_reviewer_and_acknowledge_mode_at_u(env):
    c, db = env
    au = login(c, "author1")
    ingest(c, au)
    p = draft(c, au, dev_endpoint(c, ceiling="U"))    # only the U source reaches the model
    assert p["disclosure"]["withheld_count"] == 1
    for cl in p["claims"]:
        if not cl["portion_marking"]:
            c.patch("/products/{}/claims/{}".format(p["id"], cl["id"]), headers=au,
                    json={"portion_marking": "(U)"})
    r = c.post("/products/{}/submit".format(p["id"]), headers=au)
    assert r.status_code == 200 and r.json()["citation_mode"] == "acknowledge"
    rv = login(c, "rev1")
    full = c.get("/products/" + p["id"], headers=rv).json()
    need = [cl for cl in full["claims"] if cl["needs_disposition"]]
    assert len(need) == 1
    c.post("/products/{}/claims/{}/disposition".format(p["id"], need[0]["id"]), headers=rv,
           json={"disposition": "verified_offline"})
    r = c.post("/products/{}/approve".format(p["id"]), headers=rv)
    assert r.json()["state"] == "released"                         # single reviewer at U


def test_return_and_tamper_detection(env):
    c, db = env
    au = login(c, "author1")
    ingest(c, au)
    p = draft(c, au, dev_endpoint(c, ceiling="U"))
    for cl in p["claims"]:
        if not cl["portion_marking"]:
            c.patch("/products/{}/claims/{}".format(p["id"], cl["id"]), headers=au,
                    json={"portion_marking": "(U)"})
    c.post("/products/{}/submit".format(p["id"]), headers=au)
    rv = login(c, "rev1")
    r = c.post("/products/{}/return".format(p["id"]), headers=rv, json={"note": ""})
    assert r.status_code == 422
    r = c.post("/products/{}/return".format(p["id"]), headers=rv, json={"note": "Cite the pier"})
    assert r.json()["state"] == "draft" and r.json()["return_note"] == "Cite the pier"
    ok, _, n = chain.verify(db)
    assert ok and n > 10
    ev = db.query(GovernanceEvent).filter(GovernanceEvent.event_type == "product.returned").one()
    ev.payload = dict(ev.payload, note="rewritten")
    db.commit()
    ok, bad, _ = chain.verify(db)
    assert not ok and bad == ev.seq
    r = c.get("/governance/verify", headers=login(c, "aud1"))
    assert r.json()["intact"] is False


def test_policy_bound_at_submission(env):
    c, db = env
    au = login(c, "author1")
    ingest(c, au)
    p = draft(c, au, dev_endpoint(c, ceiling="U"))
    for cl in p["claims"]:
        if not cl["portion_marking"]:
            c.patch("/products/{}/claims/{}".format(p["id"], cl["id"]), headers=au,
                    json={"portion_marking": "(U)"})
    c.post("/products/{}/submit".format(p["id"]), headers=au)
    ao = login(c, "ao1")
    s = c.get("/policy", headers=ao).json()["settings"]
    s["review_rule"]["U"] = "two_person"
    c.put("/policy", headers=ao, json={"settings": s})
    full = c.get("/products/" + p["id"], headers=login(c, "rev1")).json()
    assert full["review_rule"] == "single"
