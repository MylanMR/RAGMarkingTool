"""Runtime configuration, read from environment at call time.

Installers write these values to a service environment file
(/etc/ragmt/ragmt.env on Linux, %ProgramData%\\RagMT\\ragmt.env on Windows).
Every value has a secure default: production auth, no dev adapters, no API
docs, loopback-only binding.
"""

from __future__ import annotations

import ipaddress
import os
from typing import List

AUTH_MODE_PRODUCTION = "production"
AUTH_MODE_SCAFFOLD = "scaffold"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def auth_mode() -> str:
    """'production' (default) derives every attribute from an authenticated
    session. 'scaffold' keeps the Phase 1-5 behavior of accepting attributes
    in the request body and is refused unless RAGMT_DEV=1."""
    mode = _env("RAGMT_AUTH_MODE", AUTH_MODE_PRODUCTION).lower()
    if mode == AUTH_MODE_SCAFFOLD and dev_mode():
        return AUTH_MODE_SCAFFOLD
    return AUTH_MODE_PRODUCTION


def dev_mode() -> bool:
    return _env("RAGMT_DEV") == "1"


def enclave_networks() -> List[ipaddress._BaseNetwork]:
    """Networks treated as local for egress purposes, set by the system
    administrator at install time (comma-separated CIDRs). Loopback is always
    local and needs no entry."""
    nets = []
    for raw in _env("RAGMT_ENCLAVE_CIDRS").split(","):
        raw = raw.strip()
        if raw:
            nets.append(ipaddress.ip_network(raw, strict=False))
    return nets


def enclave_hostnames() -> List[str]:
    """Internal DNS names treated as local (exact match, case-insensitive)."""
    return [h.strip().lower() for h in _env("RAGMT_ENCLAVE_HOSTS").split(",") if h.strip()]


def ca_bundle() -> str | bool:
    """CA bundle for outbound TLS (e.g. DoD PKI roots). Verification is never
    disabled; an unset value uses the platform default store."""
    path = _env("RAGMT_CA_BUNDLE")
    return path if path else True


def llm_timeout_seconds() -> float:
    return float(_env("RAGMT_LLM_TIMEOUT", "120"))


def frontend_dist() -> str:
    return _env("RAGMT_FRONTEND_DIST")


def session_absolute_hours() -> int:
    return int(_env("RAGMT_SESSION_ABSOLUTE_HOURS", "8"))
