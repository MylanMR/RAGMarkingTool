"""Unit tests: claim parsing, marking roll-up, adapters (mocked HTTP),
egress host classification."""

import json

import httpx
import pytest

from backend.llm import adapters, egress
from backend.models.marking import PortionMarking as PM
from backend.products import claims, marking_roll


def test_claim_parser_citations_and_fabrications():
    out = claims.parse("Alpha docked. [S1] Cargo was pumps [S2, S3]. It is dangerous. [S7]\n"
                       "- Second line without cite.", 3)
    assert [c.cited for c in out] == [[1], [2, 3], [], []]
    assert out[2].invalid == ["S7"] and out[2].kind == "uncited"
    assert out[0].text == "Alpha docked." and "[S" not in out[1].text


@pytest.mark.parametrize("parts,expected", [
    (["(U)", "(S//NOFORN)"], "(S//NOFORN)"),
    (["(S//REL TO USA, GBR, AUS)", "(C//REL TO USA, GBR)"], "(S//REL TO USA, GBR)"),
    (["(S//REL TO USA, GBR)", "(S)"], "(S//NOFORN)"),
    (["(S//REL TO USA, GBR)", "(S//REL TO AUS)"], "(S//NOFORN)"),
    (["(U)", "(C//ORCON)", "(S//NOFORN)"], "(S//NOFORN/ORCON)"),
])
def test_rollup(parts, expected):
    assert str(marking_roll.combine(PM.parse(p) for p in parts)) == expected


def test_dominates():
    assert marking_roll.dominates(PM.parse("(S//NOFORN)"), PM.parse("(S//REL TO USA, GBR)"))
    assert not marking_roll.dominates(PM.parse("(S)"), PM.parse("(S//NOFORN)"))
    assert not marking_roll.dominates(PM.parse("(C//NOFORN)"), PM.parse("(S//NOFORN)"))


class EP:
    def __init__(self, adapter, base_url, model_id="m", extra=None):
        self.adapter, self.base_url, self.model_id = adapter, base_url, model_id
        self.extra, self.credential_ref, self.name = extra or {}, None, "t"


def _mock(response_json, capture):
    def h(req):
        capture["url"] = str(req.url)
        capture["headers"] = dict(req.headers)
        capture["body"] = json.loads(req.content)
        return httpx.Response(200, json=response_json)
    adapters.transport_override = httpx.MockTransport(h)


def teardown_function():
    adapters.transport_override = None


def test_gemini_adapter():
    cap = {}
    _mock({"modelVersion": "gemini-2.5-pro-001",
           "candidates": [{"content": {"parts": [{"text": "Hi [S1]"}]}}]}, cap)
    out = adapters.google_gemini(EP("google_gemini",
                                    "https://generativelanguage.googleapis.com/v1beta/models",
                                    "gemini-2.5-pro"), "k", "sys", "user")
    assert out.text == "Hi [S1]" and out.model_reported == "gemini-2.5-pro-001"
    assert cap["url"].endswith("gemini-2.5-pro:generateContent")
    assert cap["headers"]["x-goog-api-key"] == "k"


def test_anthropic_adapter():
    cap = {}
    _mock({"model": "claude-x", "content": [{"type": "text", "text": "A [S1]"}]}, cap)
    out = adapters.anthropic_messages(EP("anthropic", "https://api.anthropic.com"),
                                      "k", "sys", "u")
    assert out.text == "A [S1]" and cap["body"]["system"] == "sys"
    assert cap["headers"]["anthropic-version"] == "2023-06-01"


def test_azure_adapter():
    cap = {}
    _mock({"model": "gpt", "choices": [{"message": {"content": "B"}}]}, cap)
    adapters.azure_openai(EP("azure_openai", "https://x.openai.azure.us", "deploy1",
                             {"api_version": "2024-06-01"}), "k", "s", "u")
    assert "openai/deployments/deploy1/chat/completions" in cap["url"]
    assert "api-version=2024-06-01" in cap["url"] and cap["headers"]["api-key"] == "k"


def test_redirect_refused():
    adapters.transport_override = httpx.MockTransport(
        lambda r: httpx.Response(302, headers={"location": "https://evil.example"}))
    with pytest.raises(adapters.AdapterError, match="redirect"):
        adapters.openai_compatible(EP("openai_compatible", "https://a/v1"), None, "s", "u")


def test_credential_refs(monkeypatch, tmp_path):
    monkeypatch.setenv("K1", "abc")
    f = tmp_path / "k"
    f.write_text("xyz\n")
    assert adapters.resolve_credential("env:K1") == "abc"
    assert adapters.resolve_credential("file:" + str(f)) == "xyz"
    with pytest.raises(adapters.AdapterError):
        adapters.resolve_credential("plaintext")


def test_host_classification(monkeypatch):
    monkeypatch.setenv("RAGMT_ENCLAVE_CIDRS", "10.20.0.0/16")
    monkeypatch.setenv("RAGMT_ENCLAVE_HOSTS", "llm.enclave.local")
    assert egress._host_is_local("127.0.0.1") == (True, True)
    assert egress._host_is_local("::1") == (True, True)
    assert egress._host_is_local("10.20.4.5") == (True, False)
    assert egress._host_is_local("LLM.enclave.local") == (True, False)
    assert egress._host_is_local("10.21.0.1") == (False, False)
    assert egress._host_is_local("api.openai.com") == (False, False)


def test_dev_adapter_hidden_outside_dev(monkeypatch):
    monkeypatch.setenv("RAGMT_DEV", "0")
    assert "dev_extractive" not in adapters.available_adapters()
