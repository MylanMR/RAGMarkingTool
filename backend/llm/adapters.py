"""Model adapters. One internal interface, many providers.

Every adapter takes a system prompt and a user prompt and returns the text
plus the model identity the provider reported. HTTP goes through one client
factory that always verifies TLS (optionally against a site CA bundle such as
DoD PKI roots), never follows redirects (a redirect could move data to an
unapproved host), and applies a fixed timeout.

Adapters ship installed but every endpoint is created disabled; what may be
called is decided by the egress and ceiling checks in llm/egress.py.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Dict, Optional

import httpx

from backend import config


class AdapterError(RuntimeError):
    pass


@dataclass
class Completion:
    text: str
    model_reported: Optional[str]


# Tests inject an httpx.MockTransport here; production leaves it None.
transport_override: Optional[httpx.BaseTransport] = None


def _client() -> httpx.Client:
    return httpx.Client(timeout=config.llm_timeout_seconds(), verify=config.ca_bundle(),
                        follow_redirects=False, transport=transport_override)


def resolve_credential(ref: Optional[str]) -> Optional[str]:
    """Credentials are referenced, never stored: env:NAME or file:/path.
    Values are never logged or returned by the API."""
    if not ref:
        return None
    if ref.startswith("env:"):
        val = os.environ.get(ref[4:])
        if not val:
            raise AdapterError("credential environment variable {} is not set".format(ref[4:]))
        return val.strip()
    if ref.startswith("file:"):
        try:
            with open(ref[5:], "r", encoding="utf-8") as fh:
                return fh.read().strip()
        except OSError as exc:
            raise AdapterError("cannot read credential file: {}".format(exc)) from None
    raise AdapterError("credential_ref must start with env: or file:")


def _post(url: str, headers: Dict[str, str], body: dict, params: Optional[dict] = None) -> dict:
    with _client() as c:
        try:
            r = c.post(url, headers=headers, json=body, params=params)
        except httpx.HTTPError as exc:
            raise AdapterError("model endpoint unreachable: {}".format(type(exc).__name__)) from None
    if r.is_redirect:
        raise AdapterError("model endpoint attempted a redirect; refused")
    if r.status_code >= 400:
        raise AdapterError("model endpoint returned HTTP {}".format(r.status_code))
    try:
        return r.json()
    except ValueError:
        raise AdapterError("model endpoint returned non-JSON") from None


def _join(base: str, path: str) -> str:
    return base.rstrip("/") + "/" + path.lstrip("/")


def openai_compatible(ep, key, system, user) -> Completion:
    """OpenAI API and compatible servers: Ollama, vLLM, llama.cpp server,
    LM Studio, LocalAI. base_url is the API root, e.g. http://127.0.0.1:11434/v1"""
    headers = {"Authorization": "Bearer " + key} if key else {}
    data = _post(_join(ep.base_url, "chat/completions"), headers, {
        "model": ep.model_id, "temperature": 0,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
    try:
        return Completion(data["choices"][0]["message"]["content"], data.get("model"))
    except (KeyError, IndexError, TypeError):
        raise AdapterError("unexpected response shape from OpenAI-compatible endpoint") from None


def azure_openai(ep, key, system, user) -> Completion:
    """Azure OpenAI (commercial or Government). model_id is the deployment name."""
    api_version = (ep.extra or {}).get("api_version", "2024-06-01")
    url = _join(ep.base_url, "openai/deployments/{}/chat/completions".format(ep.model_id))
    data = _post(url, {"api-key": key or ""}, {
        "temperature": 0,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
        params={"api-version": api_version})
    try:
        return Completion(data["choices"][0]["message"]["content"], data.get("model"))
    except (KeyError, IndexError, TypeError):
        raise AdapterError("unexpected response shape from Azure OpenAI") from None


def google_gemini(ep, key, system, user) -> Completion:
    """Google Gemini API or Vertex AI. extra.auth = 'api_key' (default, x-goog-api-key)
    or 'bearer' (Vertex OAuth access token). base_url ends at the models collection,
    e.g. https://generativelanguage.googleapis.com/v1beta/models"""
    mode = (ep.extra or {}).get("auth", "api_key")
    headers = {"x-goog-api-key": key or ""} if mode == "api_key" else \
        {"Authorization": "Bearer " + (key or "")}
    data = _post(_join(ep.base_url, "{}:generateContent".format(ep.model_id)), headers, {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0}})
    try:
        parts = data["candidates"][0]["content"]["parts"]
        return Completion("".join(p.get("text", "") for p in parts), data.get("modelVersion"))
    except (KeyError, IndexError, TypeError):
        raise AdapterError("unexpected response shape from Gemini") from None


def anthropic_messages(ep, key, system, user) -> Completion:
    """Anthropic Messages API. base_url e.g. https://api.anthropic.com"""
    data = _post(_join(ep.base_url, "v1/messages"),
                 {"x-api-key": key or "", "anthropic-version": "2023-06-01"},
                 {"model": ep.model_id, "max_tokens": int((ep.extra or {}).get("max_tokens", 4096)),
                  "temperature": 0, "system": system,
                  "messages": [{"role": "user", "content": user}]})
    try:
        return Completion("".join(b.get("text", "") for b in data["content"]
                                  if b.get("type") == "text"), data.get("model"))
    except (KeyError, TypeError):
        raise AdapterError("unexpected response shape from Anthropic") from None


def aws_bedrock(ep, key, system, user) -> Completion:
    """AWS Bedrock Converse API, signed with SigV4 via botocore (optional
    dependency, bundled by the installers). Credentials come from the
    standard AWS chain of the service account; credential_ref is unused.
    base_url e.g. https://bedrock-runtime.us-gov-west-1.amazonaws.com"""
    try:
        import json as _json
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest
        from botocore.session import Session as _BotoSession
    except ImportError:
        raise AdapterError("Bedrock adapter requires botocore") from None
    region = (ep.extra or {}).get("region")
    if not region:
        raise AdapterError("Bedrock endpoint requires extra.region")
    url = _join(ep.base_url, "model/{}/converse".format(ep.model_id))
    body = {"system": [{"text": system}],
            "messages": [{"role": "user", "content": [{"text": user}]}],
            "inferenceConfig": {"temperature": 0}}
    creds = _BotoSession().get_credentials()
    if creds is None:
        raise AdapterError("no AWS credentials available to the service account")
    req = AWSRequest(method="POST", url=url, data=_json.dumps(body),
                     headers={"Content-Type": "application/json"})
    SigV4Auth(creds, "bedrock", region).add_auth(req)
    with _client() as c:
        r = c.post(url, content=req.body, headers=dict(req.headers))
    if r.status_code >= 400 or r.is_redirect:
        raise AdapterError("Bedrock returned HTTP {}".format(r.status_code))
    data = r.json()
    try:
        parts = data["output"]["message"]["content"]
        return Completion("".join(p.get("text", "") for p in parts), ep.model_id)
    except (KeyError, TypeError):
        raise AdapterError("unexpected response shape from Bedrock") from None


def dev_extractive(ep, key, system, user) -> Completion:
    """Development stand-in with no model: cites the first sentence of each
    source and adds one deliberately uncited sentence so the citation and
    review workflow can be exercised. Refused unless RAGMT_DEV=1."""
    import re
    lines = []
    for m in re.finditer(r"^\[S(\d+)\] \S+ (.+)$", user, flags=re.M):
        first = re.split(r"(?<=[.!?])\s", m.group(2).strip())[0].rstrip(".")
        lines.append("{}. [S{}]".format(first, m.group(1)))
    lines.append("Taken together, this activity is likely routine.")
    return Completion(" ".join(lines), "dev-extractive")


ADAPTERS: Dict[str, Dict[str, object]] = {
    "openai_compatible": {"fn": openai_compatible,
                          "label": "OpenAI-compatible (OpenAI, Ollama, vLLM, llama.cpp, LM Studio)"},
    "azure_openai": {"fn": azure_openai, "label": "Azure OpenAI"},
    "google_gemini": {"fn": google_gemini, "label": "Google Gemini / Vertex AI"},
    "anthropic": {"fn": anthropic_messages, "label": "Anthropic Messages API"},
    "aws_bedrock": {"fn": aws_bedrock, "label": "AWS Bedrock (Converse)"},
    "dev_extractive": {"fn": dev_extractive, "label": "Development: extractive, no model",
                       "dev_only": True},
}


def available_adapters() -> Dict[str, Dict[str, object]]:
    return {k: v for k, v in ADAPTERS.items() if config.dev_mode() or not v.get("dev_only")}


def generate(ep, system: str, user: str) -> Completion:
    spec = available_adapters().get(ep.adapter)
    if spec is None:
        raise AdapterError("adapter {!r} is not available".format(ep.adapter))
    fn: Callable = spec["fn"]
    key = None if ep.adapter in ("aws_bedrock", "dev_extractive") else \
        resolve_credential(ep.credential_ref)
    return fn(ep, key, system, user)
