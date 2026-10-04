"""Active Directory sign-in against a real MIT Kerberos KDC.

Skipped unless RAGMT_TEST_KRB=1 and a KDC for EXAMPLE.TEST is reachable with
principals alice and bob, and HTTP/ragmt.example.test in the keytab named by
RAGMT_TEST_KEYTAB. Directory (LDAP) lookups use an ldap3 mock server.
"""

import base64
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

pytestmark = pytest.mark.skipif(os.environ.get("RAGMT_TEST_KRB") != "1",
                                reason="test KDC not configured")

USERS = {"alice": "Alice-Kerberos-Pw-1", "bob": "Bob-Kerberos-Pw-1"}
G = "CN={},OU=Groups,DC=example,DC=test"
GROUP_MAP = {
    "roles": {G.format("RagMT-Authors"): ["author"], G.format("RagMT-Reviewers"): ["reviewer"],
              G.format("RagMT-Admins"): ["admin"], G.format("RagMT-AOs"): ["ao"]},
    "clearance": {G.format("Clear-S"): "S", G.format("Clear-TS"): "TS"},
    "citizenship": {G.format("US-Persons"): "USA", G.format("UK-Liaison"): "GBR"},
    "compartments": {G.format("Prog-Alpha"): "ALPHA"},
    "need_to_know": {G.format("NTK-ORCON"): "ORCON"},
}


def ticket(user, protocol="kerberos"):
    import spnego
    if protocol == "ntlm":
        c = spnego.client("alice", "x", protocol="ntlm")
    else:
        c = spnego.client("{}@EXAMPLE.TEST".format(user), USERS[user],
                          hostname="ragmt.example.test", service="HTTP", protocol="negotiate")
    return "Negotiate " + base64.b64encode(c.step()).decode()


@pytest.fixture()
def env(monkeypatch):
    from backend.api.users import UserIn, create_user
    from backend.db.database import get_session
    from backend.main import app
    from backend.models import schema
    from backend.policy import store as policy_store
    monkeypatch.setenv("RAGMT_AUTH_MODE", "production")
    monkeypatch.setenv("RAGMT_AD_ENABLED", "1")
    monkeypatch.setenv("RAGMT_AD_REALM", "EXAMPLE.TEST")
    monkeypatch.setenv("RAGMT_AD_SPN_HOST", "ragmt.example.test")
    monkeypatch.setenv("KRB5_KTNAME", os.environ.get("RAGMT_TEST_KEYTAB", "/tmp/http.keytab"))
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    schema.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    app.dependency_overrides[get_session] = lambda: (yield db)
    pol = policy_store.current(db)
    policy_store.update(db, actor="setup", settings=dict(pol.settings, system_high="S"),
                        justification="kerberos test installation at SECRET")
    db.commit()
    with TestClient(app) as c:
        yield c, db, create_user, UserIn
    app.dependency_overrides.clear()
    db.close()


def add_ad_user(env, name, roles=("author",), clearance="S"):
    c, db, create_user, UserIn = env
    create_user(db, UserIn(username=name, display_name=name.title(), auth_source="ad",
                           roles=list(roles), clearance=clearance, citizenship="USA"), actor="t")
    db.commit()


def test_providers_and_challenge(env):
    c, *_ = env
    assert c.get("/auth/providers").json()["ad"] is True
    r = c.get("/auth/negotiate")
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Negotiate"


def test_disabled_returns_404(env, monkeypatch):
    c, *_ = env
    monkeypatch.setenv("RAGMT_AD_ENABLED", "0")
    assert c.get("/auth/negotiate").status_code == 404


def test_tool_mode_kerberos_sign_in(env):
    c, *_ = env
    add_ad_user(env, "alice", clearance="S")
    r = c.get("/auth/negotiate", headers={"Authorization": ticket("alice")})
    assert r.status_code == 200, r.text
    assert r.headers["www-authenticate"].startswith("Negotiate ")      # mutual auth
    body = r.json()
    assert body["user"]["username"] == "alice" and body["user"]["must_change_password"] is False
    me = c.get("/auth/me", headers={"Authorization": "Bearer " + body["token"]})
    assert me.json()["clearance"] == "S"


def test_tool_mode_unknown_user_refused(env):
    c, db, *_ = env
    r = c.get("/auth/negotiate", headers={"Authorization": ticket("bob")})
    assert r.status_code == 403 and "refused" in r.json()["detail"]
    from backend.models.governance import GovernanceEvent
    ev = db.query(GovernanceEvent).filter(GovernanceEvent.event_type == "auth.ad_refused").one()
    assert "no tool account" in ev.payload["reason"]


def test_local_account_cannot_be_taken_over(env):
    c, db, create_user, UserIn = env
    create_user(db, UserIn(username="alice", display_name="Local Alice",
                           initial_password="Local-Account-Pass-9", roles=["admin"],
                           clearance="S", citizenship="USA"), actor="t")
    db.commit()
    assert c.get("/auth/negotiate", headers={"Authorization": ticket("alice")}).status_code == 403


def test_ntlm_refused(env):
    c, *_ = env
    add_ad_user(env, "alice")
    assert c.get("/auth/negotiate", headers={"Authorization": ticket("alice", "ntlm")}).status_code == 403


def test_garbage_and_wrong_realm_refused(env, monkeypatch):
    c, *_ = env
    add_ad_user(env, "alice")
    bad = "Negotiate " + base64.b64encode(b"\x60\x82not-a-real-token").decode()
    assert c.get("/auth/negotiate", headers={"Authorization": bad}).status_code == 403
    monkeypatch.setenv("RAGMT_AD_REALM", "OTHER.TEST")
    assert c.get("/auth/negotiate", headers={"Authorization": ticket("alice")}).status_code == 403


def test_disabled_tool_account_refused(env):
    c, db, *_ = env
    add_ad_user(env, "alice")
    from backend.models.governance import User
    db.query(User).filter(User.username == "alice").one().active = False
    db.commit()
    assert c.get("/auth/negotiate", headers={"Authorization": ticket("alice")}).status_code == 403


# --- directory mode ----------------------------------------------------------

def mock_ad(monkeypatch, entries):
    import json
    from ldap3 import MOCK_SYNC, OFFLINE_AD_2012_R2, Connection, Server
    from backend.auth import ad
    monkeypatch.setenv("RAGMT_AD_ATTRIBUTE_SOURCE", "directory")
    monkeypatch.setenv("RAGMT_AD_LDAP_BASE_DN", "DC=example,DC=test")
    monkeypatch.setenv("RAGMT_AD_GROUP_MAP", json.dumps(GROUP_MAP))

    def factory():
        conn = Connection(Server("mock", get_info=OFFLINE_AD_2012_R2), user="cn=svc",
                          password="x", client_strategy=MOCK_SYNC)
        conn.strategy.add_entry("cn=svc", {"userPassword": "x", "sAMAccountName": "svc"})
        for sam, groups, disabled in entries:
            conn.strategy.add_entry("CN={},OU=Users,DC=example,DC=test".format(sam), {
                "objectClass": ["top", "person", "user"], "sAMAccountName": sam,
                "displayName": sam.title() + " Directory", "memberOf": groups,
                "userAccountControl": 514 if disabled else 512})
        conn.bind()
        return conn
    monkeypatch.setattr(ad, "connection_factory", factory)


def test_directory_mode_provisions_and_syncs(env, monkeypatch):
    c, db, *_ = env
    groups = [G.format("RagMT-Authors"), G.format("Clear-S"), G.format("US-Persons"),
              G.format("Prog-Alpha"), G.format("NTK-ORCON")]
    mock_ad(monkeypatch, [("alice", groups, False)])
    r = c.get("/auth/negotiate", headers={"Authorization": ticket("alice")})
    assert r.status_code == 200, r.text
    u = r.json()["user"]
    assert (u["roles"], u["clearance"], u["citizenship"], u["compartments"],
            u["need_to_know_groups"], u["auth_source"]) == (
        ["author"], "S", "USA", ["ALPHA"], ["ORCON"], "ad")
    # Group removed in AD: next sign-in drops the compartment.
    mock_ad(monkeypatch, [("alice", groups[:3] + [G.format("RagMT-Reviewers")], False)])
    u = c.get("/auth/negotiate", headers={"Authorization": ticket("alice")}).json()["user"]
    assert u["compartments"] == [] and u["roles"] == ["author", "reviewer"]
    from backend.models.governance import GovernanceEvent
    assert db.query(GovernanceEvent).filter(
        GovernanceEvent.event_type == "user.directory_sync").count() == 1


@pytest.mark.parametrize("groups,reason", [
    (["RagMT-Authors", "US-Persons"], "no clearance group"),
    (["RagMT-Authors", "Clear-S"], "citizenship"),
    (["RagMT-Authors", "Clear-S", "US-Persons", "UK-Liaison"], "citizenship"),
    (["Clear-S", "US-Persons"], "no role group"),
    (["RagMT-Authors", "Clear-TS", "US-Persons"], "exceeds the system high"),
    (["RagMT-Admins", "RagMT-AOs", "Clear-S", "US-Persons"], "separate admin and AO"),
])
def test_directory_mode_fails_closed(env, monkeypatch, groups, reason):
    c, db, *_ = env
    mock_ad(monkeypatch, [("alice", [G.format(g) for g in groups], False)])
    assert c.get("/auth/negotiate", headers={"Authorization": ticket("alice")}).status_code == 403
    from backend.models.governance import GovernanceEvent, User
    ev = db.query(GovernanceEvent).filter(GovernanceEvent.event_type == "auth.ad_refused").one()
    assert reason in ev.payload["reason"]
    assert db.query(User).filter(User.username == "alice").count() == 0


def test_directory_mode_disabled_ad_account(env, monkeypatch):
    c, *_ = env
    mock_ad(monkeypatch, [("alice", [G.format("RagMT-Authors"), G.format("Clear-S"),
                                     G.format("US-Persons")], True)])
    assert c.get("/auth/negotiate", headers={"Authorization": ticket("alice")}).status_code == 403


def test_principal_normalization(monkeypatch):
    from backend.auth import ad
    monkeypatch.setenv("RAGMT_AD_REALM", "CORP.MIL")
    monkeypatch.setenv("RAGMT_AD_NETBIOS", "CORP")
    assert ad.normalize_principal("Alice@corp.mil") == "alice"
    assert ad.normalize_principal("CORP\\Alice") == "alice"
    for bad in ("alice@EVIL.MIL", "EVIL\\alice", "alice", "HTTP/host@CORP.MIL"):
        with pytest.raises(ad.ADAuthError):
            ad.normalize_principal(bad)
