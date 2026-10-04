"""Active Directory sign-in: Kerberos via SPNEGO (Integrated Windows Auth),
with optional LDAP group mapping.

Flow: the browser calls GET /auth/negotiate; the server answers 401 with
"WWW-Authenticate: Negotiate"; a domain-joined browser that trusts the site
retries with a Kerberos ticket; the server validates it and issues the same
kind of session a local sign-in gets.

Security properties:
- Kerberos only. NTLM is refused even when the client offers it (no
  relay-prone fallback). A handshake that needs more than one leg is refused.
- The ticket's realm must match RAGMT_AD_REALM.
- An AD sign-in can never land on a local account with the same username.
- Two attribute sources (RAGMT_AD_ATTRIBUTE_SOURCE):
    tool       (default) AD proves identity only. The user must already exist
               in the tool with sign-in source "ad"; clearance, citizenship,
               compartments, and roles are managed on the Users page.
    directory  Attributes and roles come from AD group membership on every
               sign-in (just-in-time provisioning). No clearance group, or
               no matching citizenship group, means no access.

Platform notes: on Windows the service validates tickets through SSPI as the
computer account (register SPN HTTP/<host> on it). On Linux, GSSAPI reads
the service keytab from KRB5_KTNAME.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from backend.models.marking import ClassificationLevel


class ADAuthError(PermissionError):
    """Sign-in refused. The message is logged; clients get a generic reply."""


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def enabled() -> bool:
    return _env("RAGMT_AD_ENABLED") == "1" and bool(_env("RAGMT_AD_REALM"))


def attribute_source() -> str:
    v = _env("RAGMT_AD_ATTRIBUTE_SOURCE", "tool").lower()
    return v if v in ("tool", "directory") else "tool"


# --------------------------------------------------------------------------
# Kerberos / SPNEGO
# --------------------------------------------------------------------------

def accept(authorization: str) -> Tuple[str, Optional[str]]:
    """Validate an 'Authorization: Negotiate <b64>' header.
    Returns (username, mutual_auth_token_b64)."""
    try:
        import spnego
    except ImportError:
        raise ADAuthError("pyspnego is not installed") from None
    if not authorization or not authorization.lower().startswith("negotiate "):
        raise ADAuthError("missing Negotiate token")
    try:
        token = base64.b64decode(authorization.split(" ", 1)[1].strip(), validate=True)
    except (ValueError, IndexError):
        raise ADAuthError("malformed Negotiate token") from None
    if token.startswith(b"NTLMSSP\x00"):
        raise ADAuthError("NTLM is refused; Kerberos is required")
    host = _env("RAGMT_AD_SPN_HOST") or None
    try:
        ctx = spnego.server(hostname=host, service="HTTP", protocol="negotiate")
        out = ctx.step(token)
    except Exception as exc:  # pyspnego raises several types; all mean refusal
        raise ADAuthError("ticket validation failed: {}".format(type(exc).__name__)) from None
    if not ctx.complete:
        raise ADAuthError("multi-leg authentication refused (Kerberos is single-leg)")
    if (getattr(ctx, "negotiated_protocol", "") or "").lower() != "kerberos":
        raise ADAuthError("negotiated protocol {!r} refused; Kerberos is required"
                          .format(getattr(ctx, "negotiated_protocol", None)))
    username = normalize_principal(ctx.client_principal or "")
    return username, base64.b64encode(out).decode() if out else None


def normalize_principal(principal: str) -> str:
    """'alice@CORP.MIL' or 'CORP\\alice' -> 'alice', after checking the realm."""
    realm = _env("RAGMT_AD_REALM").upper()
    netbios = _env("RAGMT_AD_NETBIOS").upper()
    p = principal.strip()
    if "\\" in p:
        dom, user = p.split("\\", 1)
        if not netbios or dom.upper() != netbios:
            raise ADAuthError("principal domain {!r} is not the configured domain".format(dom))
    elif "@" in p:
        user, r = p.rsplit("@", 1)
        if r.upper() != realm:
            raise ADAuthError("principal realm {!r} is not {}".format(r, realm))
    else:
        raise ADAuthError("principal {!r} has no realm".format(p))
    if not user or "/" in user:
        raise ADAuthError("service principals cannot sign in")
    return user.lower()


# --------------------------------------------------------------------------
# Directory (LDAP) group mapping
# --------------------------------------------------------------------------

@dataclass
class DirectoryProfile:
    username: str
    display_name: str
    roles: List[str]
    clearance: str
    citizenship: str
    compartments: List[str] = field(default_factory=list)
    need_to_know_groups: List[str] = field(default_factory=list)
    groups: List[str] = field(default_factory=list)


def group_map() -> Dict[str, Dict[str, object]]:
    raw = _env("RAGMT_AD_GROUP_MAP")
    if not raw:
        raise ADAuthError("RAGMT_AD_GROUP_MAP is required for directory attributes")
    if raw.startswith("file:"):
        with open(raw[5:], encoding="utf-8") as fh:
            raw = fh.read()
    data = json.loads(raw)
    norm = {}
    for section in ("roles", "clearance", "citizenship", "compartments", "need_to_know"):
        norm[section] = {k.strip().lower(): v for k, v in (data.get(section) or {}).items()}
    return norm


def map_groups(username: str, display_name: str, groups: List[str],
               gmap: Dict[str, Dict[str, object]]) -> DirectoryProfile:
    gs = {g.strip().lower() for g in groups}
    roles: List[str] = []
    for dn, rs in gmap["roles"].items():
        if dn in gs:
            roles.extend(r for r in (rs if isinstance(rs, list) else [rs]) if r not in roles)
    levels = [ClassificationLevel.parse(v) for dn, v in gmap["clearance"].items() if dn in gs]
    if not levels:
        raise ADAuthError("no clearance group for {}".format(username))
    clearance = max(levels, key=lambda lv: lv.rank).value
    cits = sorted({str(v).upper() for dn, v in gmap["citizenship"].items() if dn in gs})
    if len(cits) != 1:
        raise ADAuthError("{} matched {} citizenship groups; exactly 1 is required"
                          .format(username, len(cits)))
    comps = sorted({str(v) for dn, v in gmap["compartments"].items() if dn in gs})
    ntk = sorted({str(v) for dn, v in gmap["need_to_know"].items() if dn in gs})
    if not roles:
        raise ADAuthError("no role group for {}".format(username))
    return DirectoryProfile(username=username, display_name=display_name or username,
                            roles=sorted(roles), clearance=clearance, citizenship=cits[0],
                            compartments=comps, need_to_know_groups=ntk, groups=sorted(gs))


def _default_connection():
    """Bind to AD over LDAPS. RAGMT_AD_LDAP_BIND=kerberos (default) binds as
    the service's own Kerberos identity; 'simple' uses a service account DN
    and a referenced password."""
    import ssl
    from ldap3 import KERBEROS, SASL, Connection, Server, Tls
    from backend.llm.adapters import resolve_credential
    url = _env("RAGMT_AD_LDAP_URL")
    if not url.lower().startswith("ldaps://"):
        raise ADAuthError("RAGMT_AD_LDAP_URL must use ldaps://")
    tls = Tls(validate=ssl.CERT_REQUIRED, ca_certs_file=_env("RAGMT_CA_BUNDLE") or None)
    server = Server(url, use_ssl=True, tls=tls, connect_timeout=10)
    if _env("RAGMT_AD_LDAP_BIND", "kerberos") == "simple":
        conn = Connection(server, user=_env("RAGMT_AD_LDAP_BIND_DN"),
                          password=resolve_credential(_env("RAGMT_AD_LDAP_PASSWORD_REF")),
                          auto_bind=True, receive_timeout=15)
    else:
        conn = Connection(server, authentication=SASL, sasl_mechanism=KERBEROS,
                          auto_bind=True, receive_timeout=15)
    return conn


# Tests replace this with an ldap3 MOCK_SYNC connection.
connection_factory: Callable = _default_connection


def directory_lookup(username: str) -> DirectoryProfile:
    from ldap3.utils.conv import escape_filter_chars
    base = _env("RAGMT_AD_LDAP_BASE_DN")
    if not base:
        raise ADAuthError("RAGMT_AD_LDAP_BASE_DN is required")
    conn = connection_factory()
    try:
        conn.search(base, "(&(objectClass=user)(sAMAccountName={}))".format(
            escape_filter_chars(username)), attributes=["displayName", "memberOf",
                                                        "userAccountControl"])
        if len(conn.entries) != 1:
            raise ADAuthError("directory has {} entries for {}".format(len(conn.entries), username))
        e = conn.entries[0]
        uac = int(e.userAccountControl.value or 0) if "userAccountControl" in e else 0
        if uac & 0x2:
            raise ADAuthError("directory account {} is disabled".format(username))
        groups = [str(g) for g in (e.memberOf.values if "memberOf" in e else [])]
        if _env("RAGMT_AD_NESTED_GROUPS") == "1":
            # LDAP_MATCHING_RULE_IN_CHAIN: every group the user is in, transitively.
            conn.search(base, "(&(objectClass=group)(member:1.2.840.113556.1.4.1941:={}))"
                        .format(escape_filter_chars(e.entry_dn)), attributes=["cn"])
            groups = sorted({*groups, *(x.entry_dn for x in conn.entries)})
        name = str(e.displayName.value) if "displayName" in e and e.displayName.value else username
    finally:
        try:
            conn.unbind()
        except Exception:
            pass
    return map_groups(username, name, groups, group_map())
