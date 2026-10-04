"""Egress and classification-ceiling enforcement for model calls.

Two independent gates run before any prompt leaves the process:

1. Egress: under 'local_only' the endpoint host must be loopback or inside a
   declared enclave network/hostname. Under 'allowlist' a non-local endpoint
   must also carry an AO approval. Non-loopback endpoints must use HTTPS.
2. Ceiling: retrieved chunks above the effective ceiling are withheld from the
   prompt. Effective ceiling is the endpoint's approved level ('enforced') or
   the system high ('system_high'), and never above the system high.
"""

from __future__ import annotations

import ipaddress
from typing import List, Tuple
from urllib.parse import urlparse

from backend import config
from backend.policy import catalog


class EgressDenied(PermissionError):
    pass


def _host_is_local(host: str) -> Tuple[bool, bool]:
    """Return (local, loopback)."""
    h = (host or "").strip("[]").lower()
    if h in ("localhost",):
        return True, True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return h in config.enclave_hostnames(), False
    if ip.is_loopback:
        return True, True
    return any(ip in net for net in config.enclave_networks()), False


def check(endpoint, policy) -> None:
    if not endpoint.enabled:
        raise EgressDenied("model endpoint {!r} is disabled".format(endpoint.name))
    if endpoint.adapter == "dev_extractive":
        if not config.dev_mode():
            raise EgressDenied("development adapter is not permitted outside dev mode")
        return
    url = urlparse(endpoint.base_url)
    if url.scheme not in ("http", "https") or not url.hostname:
        raise EgressDenied("endpoint URL must be http(s)://host/...")
    local, loopback = _host_is_local(url.hostname)
    if url.scheme != "https" and not loopback:
        raise EgressDenied("non-loopback model endpoints must use HTTPS")
    mode = policy.get("egress_mode")
    if mode == "local_only" and not local:
        raise EgressDenied(
            "egress policy is local-only; {} is not loopback or a declared enclave network"
            .format(url.hostname))
    if mode == "allowlist" and not local and not endpoint.approved_by:
        raise EgressDenied("non-local endpoint {!r} has not been approved by an AO"
                           .format(endpoint.name))
    if catalog.level_rank(endpoint.max_classification) > catalog.level_rank(policy.system_high):
        raise EgressDenied("endpoint ceiling {} exceeds system high {}"
                           .format(endpoint.max_classification, policy.system_high))


def effective_ceiling(endpoint, policy) -> str:
    if policy.get("model_ceiling_mode") == "system_high":
        return policy.system_high
    sh = policy.system_high
    ep = endpoint.max_classification
    return ep if catalog.level_rank(ep) <= catalog.level_rank(sh) else sh


def split_by_ceiling(hits: List, ceiling: str) -> Tuple[List, List]:
    limit = catalog.level_rank(ceiling)
    allowed = [h for h in hits if catalog.level_rank(h.classification) <= limit]
    withheld = [h for h in hits if catalog.level_rank(h.classification) > limit]
    return allowed, withheld
