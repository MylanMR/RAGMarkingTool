"""Identity provider interface.

Every provider resolves a sign-in to an ExternalIdentity; the tool then maps
it to a local User row, which is the single place attributes (clearance,
citizenship, compartments, need-to-know) come from. The PDP never sees
client-supplied attributes in production mode.

Status:
- Local accounts: implemented (backend/api/auth.py).
- Active Directory: implemented in backend/auth/ad.py (Kerberos via SPNEGO,
  optional LDAP group mapping) and exposed at GET /auth/negotiate.
- OidcProvider, SamlProvider: interface and configuration schema defined,
  NOT IMPLEMENTED. They raise ProviderNotAvailable so a misconfigured
  deployment fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


class ProviderNotAvailable(RuntimeError):
    pass


@dataclass
class ExternalIdentity:
    username: str
    display_name: str
    source: str                                  # ad | oidc | saml
    groups: List[str] = field(default_factory=list)
    claims: Dict[str, object] = field(default_factory=dict)


# Configuration each external provider will read (documented for installers).
CONFIG_SCHEMA = {
    "ad": {
        "RAGMT_AD_ENABLED": "1 to offer Windows sign-in",
        "RAGMT_AD_REALM": "Kerberos realm, e.g. CORP.EXAMPLE.MIL",
        "RAGMT_AD_NETBIOS": "NetBIOS domain for DOMAIN\\user principals (Windows SSPI)",
        "RAGMT_AD_SPN_HOST": "Host part of the HTTP SPN, e.g. ragmt.corp.example.mil",
        "KRB5_KTNAME": "Linux only: service keytab path",
        "RAGMT_AD_ATTRIBUTE_SOURCE": "tool (default) or directory",
        "RAGMT_AD_LDAP_URL": "ldaps://dc.corp.example.mil (directory mode)",
        "RAGMT_AD_LDAP_BASE_DN": "DC=corp,DC=example,DC=mil",
        "RAGMT_AD_LDAP_BIND": "kerberos (default) or simple",
        "RAGMT_AD_LDAP_BIND_DN / RAGMT_AD_LDAP_PASSWORD_REF": "simple bind only",
        "RAGMT_AD_NESTED_GROUPS": "1 to resolve nested groups",
        "RAGMT_AD_GROUP_MAP": "JSON or file:/path mapping group DNs to roles and attributes",
    },
    "oidc": {
        "RAGMT_OIDC_ISSUER": "Issuer URL",
        "RAGMT_OIDC_CLIENT_ID": "Client ID",
        "RAGMT_OIDC_CLIENT_SECRET_REF": "env:NAME or file:/path",
        "RAGMT_OIDC_CLAIM_MAP": "JSON: claim -> role / attribute mapping",
    },
    "saml": {
        "RAGMT_SAML_IDP_METADATA": "IdP metadata XML path",
        "RAGMT_SAML_SP_ENTITY_ID": "SP entity ID",
        "RAGMT_SAML_ATTRIBUTE_MAP": "JSON: SAML attribute -> role / attribute mapping",
    },
}


class _Unavailable:
    source = ""

    def authenticate(self, request) -> ExternalIdentity:  # pragma: no cover - stub
        raise ProviderNotAvailable(
            "{} sign-in is defined but not implemented in this release".format(self.source))


class OidcProvider(_Unavailable):
    source = "oidc"


class SamlProvider(_Unavailable):
    source = "saml"


EXTERNAL_PROVIDERS = {"oidc": OidcProvider, "saml": SamlProvider}
