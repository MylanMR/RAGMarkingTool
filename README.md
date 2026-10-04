# Classification-Aware RAG Marking Tool

Version 0.2.1, 4 Oct 2026

A classification-aware retrieval and drafting add-on that works with any LLM. Markings are applied at intake, inherited by every chunk, enforced at query time by a policy decision point (PDP), and carried through to anything a model drafts. Model-assisted products can't leave the tool until a human other than the author has reviewed them under rules the Authorizing Official (AO) selects.

> **Not accredited.** The PDP, marking roll-up rules, and access control need independent security review before this tool touches real classified data. See [Known limitations and review items](#known-limitations-and-review-items).

End-user instructions are in [USER_MANUAL.md](USER_MANUAL.md) (PDF build: `tools/build_manual_pdf.py`).

## Why v0.2 exists

In spring 2026, a model-assisted intelligence report misidentified a vessel's cargo, fused open-source and SIGINT inputs without lineage, and reached operational planning before anyone learned a model wrote it. v0.2 adds the two controls that incident lacked:

1. **Provenance on every claim.** Model output is split into sentence-level claims. Each claim must cite a numbered source the user was authorized to see, or it is flagged. Citations to sources that don't exist are caught and never count as support. Every product carries a "Derived From" source list and an AI-assistance disclosure (model, endpoint, reported model version, prompt hash, ceiling applied).
2. **A release gate before anything moves.** No model-assisted product is exportable as released until it passes review. The author can never approve or release their own work, and the policy in force is bound at submission.

## Status

| Phase | Scope | Status |
|---|---|---|
| 1 to 5 | Intake, marking inheritance, filtered vector search, PDP, query audit log | Built (v0.1) |
| 6 | Integration tests across phases | Built |
| 7 | Production authentication: local accounts, sessions, roles, lockout | Built |
| 8 | AO risk policy (drop-down controls, versioned, justification on relaxation) | Built |
| 9 | Model adapters, egress control, per-model classification ceilings | Built |
| 10 | Claim/citation enforcement, marking roll-up, release gate, marked export, hash-chained governance log | Built |
| 11a | Active Directory sign-in (Kerberos via SPNEGO, optional LDAP group mapping) | Built; tested against a live MIT KDC |
| 11b | OIDC and SAML sign-in | Interface and config schema only, **not functional** |
| 12 | Windows and Linux offline installers | Database steps replayed live on Postgres 16 (found and fixed a role-creation bug); full scripts **not yet run on a target host** |

Test suite: 201 tests, all passing on 4 Oct 2026.

| Suite | Tests | Runs against |
|---|---|---|
| v0.1 and v0.2 core | 178 | sqlite (always runs) |
| `test_postgres_live.py` | 6 | PostgreSQL 16.x + pgvector, connected as the least-privilege `ragmt_app` role, after the installer's exact database steps |
| `test_ad_kerberos.py` | 17 | A live MIT Kerberos KDC (real tickets, SPNEGO, mutual auth); LDAP through an ldap3 mock |

The live suites skip unless configured (see [Development](#development)). The Postgres suite confirmed: marking filters run inside the pgvector similarity query; the full draft-to-release workflow works; the service role is denied `UPDATE`, `DELETE`, `DROP TRIGGER`, and `CREATE TABLE`; the append-only trigger stops even the schema owner; the separation-of-duties `CHECK` constraint fires; and 6 concurrent writers produce an intact hash chain. Removing the advisory lock makes that last test fail (chain forks), so the test is known to detect the problem.

## Architecture

```
Browser (React, served by the app)
   |  HTTPS, bearer session token held in memory only
FastAPI service  (runs as NT SERVICE\RagMT or the ragmt system user)
   |-- auth/        local sign-in, sessions, role checks, provider interface
   |-- policy/      AO-selectable controls, versioned
   |-- retrieval/   PDP-built filter, in-query enforcement, per-hit re-check
   |-- llm/         adapters, egress gate, classification ceiling
   |-- products/    claim parser, marking roll-up, release workflow, export
   |-- governance/  SHA-256 hash-chained event log
   |
PostgreSQL 16 + pgvector  (127.0.0.1 only, scram-sha-256, separate service account)
   |-- ragmt_owner: owns schema, runs migrations
   |-- ragmt_app:   service login, append-only on audit and governance tables
   |
Model endpoints (local Ollama/vLLM, enclave servers, or AO-approved cloud)
```

Drafting flow: question, then PDP-filtered retrieval (audited), then sources above the model's ceiling are withheld, then the model is prompted with numbered, portion-marked sources, then the output is parsed into claims, each cited claim gets a marking floor rolled up from its sources, and the product is stored as a draft. Uncited claims stay unmarked until the author marks them.

## Security design

### Invariants that hold under every policy setting

- **No silent defaults.** No code path assigns a classification. Uncited claims start unmarked; submission refuses any unmarked claim. A cited claim's marking can't go below the roll-up of its sources.
- **Attributes come from identity.** In production mode the PDP evaluates the signed-in user's stored clearance, citizenship, compartments, and need-to-know groups. Attributes in a request body are ignored. Scaffold mode (body attributes) only runs with `RAGMT_DEV=1`, and the production launcher refuses to start in dev mode.
- **Fail-closed auditing.** Query audit rows and governance events commit in the same transaction as the action. If the record can't be written, the action doesn't happen.
- **Separation of duties.** The author can't disposition, approve, return, or release their own product. Under two-person review, the releaser must differ from both author and reviewer. Postgres `CHECK` constraints back this up.
- **Policy binding.** A product is judged by the policy version in force when it was submitted. Content changes after submission invalidate review (SHA-256 content check).
- **Read access follows markings.** Viewing a product is a PDP decision on the roll-up of every source it used. Unauthorized users get the same 404 as a missing product.
- **Secrets are referenced.** Model credentials are stored as `env:NAME` or `file:/path` references and read at call time. The API rejects a raw key.
- **Egress hygiene.** Outbound model calls always verify TLS (optionally against a site CA bundle such as DoD PKI roots), never follow redirects, and must use HTTPS unless the endpoint is loopback.
- **Tamper evidence.** Each governance event hashes its predecessor. `GET /governance/verify` or `python -m backend.cli verify-chain` finds the first altered row. On Postgres a trigger blocks `UPDATE` and `DELETE` on the table, and the service role has only `SELECT, INSERT`.

### AO-selectable controls

All options are drop-downs on the Risk policy page. Choosing a less strict option than the saved one requires a written justification (20+ characters). Every version is kept.

| Control | Options (strictest first) | Default |
|---|---|---|
| Citation enforcement, per level | Block / Flag and acknowledge / Advisory | Acknowledge at U and C; Block at S, TS, TS/SCI |
| Release review rule, per level | Two-person / Single reviewer | Single at U and C; Two-person at S and above |
| Model classification ceiling | Enforced per model / System-high | Enforced |
| Model network egress | Local and enclave only / AO-approved allowlist | Local only |
| System high | U, C, S, TS, TS/SCI | U (installer sets the real value) |
| Session idle timeout | 15 / 30 / 60 minutes | 15 |
| Failed sign-in lockout | 3 / 5 / 10 attempts | 3 |
| Admin and AO role separation | Separate / May combine | Separate |

Not configurable: the release gate, AI-assistance disclosure, fail-closed auditing, PDP filtering, and author self-approval. "System-high" ceiling mode replaces "no ceiling" on purpose: it lets an enclave treat every model as approved to the system high without ever sending content above the accreditation boundary.

### Roles

| Role | Can |
|---|---|
| author | Ingest documents, search, draft with a model, mark and edit own drafts, submit |
| reviewer | Disposition flagged claims, approve, return |
| releaser | Release approved products (two-person rule), return |
| admin | Manage users and model endpoints |
| ao | Change risk policy, approve or revoke non-local model endpoints |
| auditor | Read governance log, query audit log, users, and policy history |

### Data at rest

PostgreSQL doesn't encrypt its data files on its own. Install on a volume protected by BitLocker (Windows) or LUKS/dm-crypt (Linux) to meet SC-28.

## Supported platforms

| Platform | Notes |
|---|---|
| Windows Server 2019, 2022, 2025 | Build 17763 or later; installer checks |
| Windows 11 | Same installer |
| Linux x86_64, glibc 2.28+ | RHEL/Rocky/Alma 8 and 9, Ubuntu 20.04+; systemd required |

Runtime: Python 3.12 (embedded on Windows, python-build-standalone on Linux), PostgreSQL 16, pgvector 0.7. Linux containers aren't used because Windows Server 2019 can't run them natively.

## Installation

Both installers work offline. You stage a bundle on a connected build host, move it through your approved transfer process, and install. Every file is checked against a SHA-256 manifest before anything is extracted.

### Windows

1. **Build pgvector once** (it has no official Windows binaries). On the build host, install Visual Studio Build Tools with the C++ workload, open "x64 Native Tools Command Prompt", then:
   ```
   set "PGROOT=C:\path\to\extracted\pgsql"
   git clone --branch v0.7.4 https://github.com/pgvector/pgvector.git
   cd pgvector
   nmake /F Makefile.win
   ```
   Keep the folder with `vector.dll`, `vector.control`, and `vector--*.sql`.
2. **Stage the bundle** (needs Python 3.12, Node 18+, internet):
   ```powershell
   .\installer\windows\build-bundle.ps1 -PgvectorBuildDir C:\build\pgvector
   ```
   Record the printed SHA-256 of `SHA256SUMS.txt` in your transfer paperwork.
3. **Install** on the target from an elevated PowerShell prompt in the bundle folder:
   ```powershell
   .\install.ps1 -SystemHigh S
   # Network access with TLS:
   .\install.ps1 -SystemHigh S -Bind 0.0.0.0 -TlsCertPem C:\certs\ragmt.pem -TlsKeyPem C:\certs\ragmt.key `
       -EnclaveCidrs "10.20.0.0/16" -CaBundle C:\certs\dod-roots.pem
   ```
   The installer creates two virtual service accounts (`NT SERVICE\RagMT-Postgres`, `NT SERVICE\RagMT`), initializes Postgres on 127.0.0.1:54329, applies migrations and least-privilege roles, sets the system high, prompts for the first admin and AO accounts, registers the app as a Windows service through WinSW, and opens the firewall port only when not bound to loopback.
4. **Remove** with `uninstall.ps1`. Data in `%ProgramData%\RagMT` is preserved for records retention.

### Linux

1. **Stage** on a connected host of the same distro family (needs gcc, make, openssl-devel or libssl-dev, readline and zlib headers, Node 18+):
   ```bash
   ./installer/linux/build-bundle.sh ./ragmt-bundle-linux
   ```
2. **Install** as root in the bundle folder:
   ```bash
   sudo ./install.sh --system-high S
   sudo ./install.sh --system-high S --bind 0.0.0.0 --tls-cert /etc/pki/ragmt.pem --tls-key /etc/pki/ragmt.key \
        --enclave-cidrs 10.20.0.0/16 --ca-bundle /etc/pki/dod-roots.pem
   ```
   The installer creates `ragmt` and `ragmt-pg` system users, installs to `/opt/ragmt`, keeps data in `/var/lib/ragmt`, writes `/etc/ragmt/ragmt.env` (mode 0640, root:ragmt), and installs hardened systemd units (`ProtectSystem=strict`, `NoNewPrivileges`, empty capability set, private /tmp and devices).
3. On SELinux-enforcing hosts, label `/opt/ragmt` and `/var/lib/ragmt` per your site policy before starting the services.

## Configuration reference

The installers write these to the service environment. All have secure defaults.

| Variable | Purpose | Default |
|---|---|---|
| `DATABASE_URL` | SQLAlchemy URL; service uses the `ragmt_app` role | local Postgres |
| `VECTOR_STORE` | `pgvector` (production) or `memory` (dev) | `pgvector` |
| `RAGMT_AUTH_MODE` | `production`, or `scaffold` (dev only, ignored unless `RAGMT_DEV=1`) | `production` |
| `RAGMT_DEV` | `1` enables API docs, scaffold mode, and the dev model adapter | unset |
| `RAGMT_BIND`, `RAGMT_PORT` | Listen address and port; non-loopback requires TLS | `127.0.0.1`, `8443` |
| `RAGMT_TLS_CERT`, `RAGMT_TLS_KEY` | PEM files for HTTPS | unset |
| `RAGMT_ENCLAVE_CIDRS` | Networks treated as local for egress (comma-separated) | none |
| `RAGMT_ENCLAVE_HOSTS` | Internal hostnames treated as local | none |
| `RAGMT_CA_BUNDLE` | CA bundle for outbound TLS (e.g. DoD roots) | platform store |
| `RAGMT_LLM_TIMEOUT` | Seconds per model call | `120` |
| `RAGMT_SESSION_ABSOLUTE_HOURS` | Maximum session lifetime | `8` |
| `RAGMT_FRONTEND_DIST` | Built UI folder to serve | set by installer |
| `RAGMT_AD_ENABLED`, `RAGMT_AD_REALM`, `RAGMT_AD_NETBIOS`, `RAGMT_AD_SPN_HOST` | Windows sign-in | off |
| `KRB5_KTNAME` | Linux service keytab | unset |
| `RAGMT_AD_ATTRIBUTE_SOURCE` | `tool` or `directory` | `tool` |
| `RAGMT_AD_LDAP_URL`, `RAGMT_AD_LDAP_BASE_DN`, `RAGMT_AD_LDAP_BIND`, `RAGMT_AD_NESTED_GROUPS`, `RAGMT_AD_GROUP_MAP` | Directory mode | unset |

## Model endpoints

Admins add endpoints on the Models page; every endpoint starts disabled. Under the allowlist egress policy, any endpoint outside the host or declared enclave networks also needs AO approval, and editing its address, model, adapter, or ceiling clears that approval.

| Adapter | Base URL example | Model ID | Credential | Options (JSON) |
|---|---|---|---|---|
| OpenAI-compatible | `http://127.0.0.1:11434/v1` (Ollama), `https://vllm.enclave/v1`, `https://api.openai.com/v1` | model name | `env:OPENAI_API_KEY` or none for local | none |
| Azure OpenAI | `https://<resource>.openai.azure.us` | deployment name | `env:AZURE_OPENAI_KEY` | `{"api_version": "2024-06-01"}` |
| Google Gemini / Vertex | `https://generativelanguage.googleapis.com/v1beta/models` or a Vertex `.../publishers/google/models` URL | `gemini-...` | API key, or a Vertex access token with `{"auth": "bearer"}` | `{"auth": "api_key"}` |
| Anthropic | `https://api.anthropic.com` | model name | `env:ANTHROPIC_API_KEY` | `{"max_tokens": 4096}` |
| AWS Bedrock | `https://bedrock-runtime.<region>.amazonaws.com` | model ID | service account's AWS credential chain | `{"region": "us-gov-west-1"}` |
| Development (dev only) | `local://dev` | any | none | none |

Vertex access tokens expire; for unattended use, point `credential_ref` at a file your token-refresh job rewrites.

## Identity providers

Local accounts are fully implemented: PBKDF2-HMAC-SHA256 (600,000 iterations; stdlib, FIPS-approved primitive), 15-character minimum with 3 of 4 character classes, generic failure messages, policy-driven lockout, forced change of admin-issued passwords, server-side sessions storing only token hashes.

### Active Directory (Windows sign-in)

Users on domain-joined machines select **Sign in with Windows**. The browser sends a Kerberos ticket (SPNEGO), the service validates it, and the user gets a normal session. Properties:

- **Kerberos only.** NTLM is refused, including NTLM offered inside SPNEGO. Multi-leg handshakes are refused.
- **Realm pinned.** Tickets from any realm other than `RAGMT_AD_REALM` are refused. Service principals can't sign in.
- **No account takeover.** An AD identity can never sign in to a local account with the same username.
- **Mutual authentication.** The server returns its own Kerberos token so the browser can verify it.
- Every refusal is written to the governance log with the reason; the browser only sees a generic message.

Choose where attributes come from with `RAGMT_AD_ATTRIBUTE_SOURCE`:

| Mode | Behavior | Use when |
|---|---|---|
| `tool` (default) | AD proves identity only. An admin pre-creates the user with sign-in source "Active Directory" and sets clearance, citizenship, compartments, and roles in the tool. Unknown users are refused. | Clearance data isn't maintained in AD groups, or you want the tool's admin to control access |
| `directory` | Roles and attributes come from AD group membership at every sign-in (just-in-time provisioning). Changes are logged as `user.directory_sync`. No clearance group, zero or several citizenship groups, no role group, clearance above system high, or admin+AO under role separation: refused. | AD groups are the authoritative access record |

Directory mode reads a group map (JSON, or `file:/path`):

```json
{
  "roles":        {"CN=RagMT-Authors,OU=Groups,DC=corp,DC=mil": ["author"],
                   "CN=RagMT-Reviewers,OU=Groups,DC=corp,DC=mil": ["reviewer"]},
  "clearance":    {"CN=Clear-S,OU=Groups,DC=corp,DC=mil": "S",
                   "CN=Clear-TS,OU=Groups,DC=corp,DC=mil": "TS"},
  "citizenship":  {"CN=US-Persons,OU=Groups,DC=corp,DC=mil": "USA"},
  "compartments": {"CN=Prog-Alpha,OU=Groups,DC=corp,DC=mil": "ALPHA"},
  "need_to_know": {"CN=NTK-ORCON,OU=Groups,DC=corp,DC=mil": "ORCON"}
}
```

The highest matching clearance wins. LDAP connections must use `ldaps://` with certificate validation (`RAGMT_CA_BUNDLE`), and bind with the service's own Kerberos identity by default (`RAGMT_AD_LDAP_BIND=kerberos`). Set `RAGMT_AD_NESTED_GROUPS=1` to resolve nested groups. Disabled AD accounts (userAccountControl bit 2) are refused.

**Windows setup.** Register the SPN on the server's computer account (`setspn -S HTTP/ragmt.corp.mil RAGMT01$`), install with `-AdRealm CORP.MIL -AdNetbios CORP -AdSpnHost ragmt.corp.mil`, and add the site to the browsers' Local Intranet zone (or `AuthServerAllowlist` for Edge and Chrome) by GPO.

**Linux setup.** Create a keytab for `HTTP/ragmt.corp.mil` (`ktpass` on a DC, or `adcli`), then install with `--ad-realm CORP.MIL --ad-spn-host ragmt.corp.mil --ad-keytab /root/http.keytab`. The installer copies it to `/etc/ragmt/http.keytab` (0640, root:ragmt) and sets `KRB5_KTNAME`.

### OIDC and SAML

Defined in `backend/auth/providers.py` with the configuration each will read (`CONFIG_SCHEMA`). They raise `ProviderNotAvailable`, so a deployment configured for them fails closed.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest                    # 178 tests on sqlite; live suites skip
.venv/bin/python -m backend.dev               # API on :8000, sqlite dev.db, dev mode
cd frontend && npm install && npm run dev     # UI on :5173, proxies to :8000
```

Live suites:
```bash
# Postgres: apply migrations and installer/common/roles.sql first, as the installers do
RAGMT_TEST_PG_APP_URL=postgresql+psycopg2://ragmt_app:...@127.0.0.1:54329/ragmt \
RAGMT_TEST_PG_OWNER_URL=postgresql+psycopg2://ragmt_owner:...@127.0.0.1:54329/ragmt \
  .venv/bin/python -m pytest tests/test_postgres_live.py
# Kerberos: MIT KDC for EXAMPLE.TEST with principals alice, bob, HTTP/ragmt.example.test
RAGMT_TEST_KRB=1 RAGMT_TEST_KEYTAB=/tmp/http.keytab .venv/bin/python -m pytest tests/test_ad_kerberos.py
```

Seed a dev admin:
```bash
DATABASE_URL=sqlite:///./dev.db RAGMT_DEV=1 .venv/bin/python -m backend.cli create-user \
  --username dev-admin --display-name "Dev Admin" --roles admin,author --clearance S --citizenship USA
```
Then sign in, set the system high on the Risk policy page (as an AO account), and add a "Development: extractive, no model" endpoint to exercise the workflow without an LLM.

## API summary

| Area | Endpoints |
|---|---|
| Auth | `GET /auth/providers`, `POST /auth/login`, `GET /auth/negotiate`, `POST /auth/logout`, `GET /auth/me`, `POST /auth/password` |
| Users | `GET/POST /users`, `PATCH /users/{id}`, `POST /users/{id}/unlock`, `POST /users/{id}/reset-password` |
| Policy | `GET/PUT /policy`, `GET /policy/history` |
| Models | `GET /models/adapters`, `GET/POST /models`, `PATCH /models/{id}`, `POST /models/{id}/approve`, `POST /models/{id}/revoke` |
| Products | `POST /products`, `GET /products?view=mine\|review\|release\|released`, `GET /products/{id}`, `PATCH/DELETE /products/{id}/claims/{cid}`, `POST /products/{id}/submit`, `POST /products/{id}/claims/{cid}/disposition`, `POST /products/{id}/approve\|release\|return`, `GET /products/{id}/export` |
| Governance | `GET /governance/events`, `GET /governance/verify` |
| v0.1 | `POST /ingest/documents`, `POST /ingest/documents/{id}/embed`, `POST /query`, `GET /audit/queries[/{id}]` |

## Known limitations and review items

These need resolution or an explicit risk decision before an ATO.

1. **Independent review of the PDP and marking logic** (carried from v0.1). Placeholder semantics remain for ORCON/PROPIN/RELIDO/NOCON (modeled as need-to-know groups), SCI control systems (not modeled), and dual citizenship (not modeled).
2. **Marking roll-up is conservative and simplified.** Mixed REL TO and unmarked classified portions roll up to NOFORN. Declassification instructions are not computed; exports say to verify against sources.
3. **Model ceilings check classification level only.** Dissemination controls are not evaluated per model. A NOFORN chunk can reach any model whose ceiling covers its level, so foreign-hosted or foreign-operated endpoints must not be approved.
4. **Citation checks are structural.** The tool verifies a claim cites a real, authorized source; it does not verify the source supports the claim. That stays a reviewer responsibility, which is why dispositions exist.
5. **Installers are untested on target hosts.** The PowerShell installer has not been executed (no Windows host was available during build). The Linux scripts pass `bash -n` but have not run end to end. Plan a test install on Server 2019, Windows 11, and RHEL 8/9 before fielding.
6. **AD tested against MIT Kerberos and a mock LDAP server.** Still needs a pass against a real Windows domain controller: SSPI on Windows Server, `DOMAIN\user` principals, real `memberOf` and nested-group results, and LDAPS with a DoD-issued DC certificate.
7. **OIDC and SAML** are not functional.
8. **No FIPS-mode validation.** PBKDF2 and SHA-256 are approved algorithms, but the Python and OpenSSL builds bundled by the installers are not FIPS 140-validated modules. Sites requiring validated crypto need a validated OpenSSL and a FIPS-enabled OS.
9. **Session tokens live in browser memory.** Refreshing the page signs the user out by design. A strict CSP limits script injection, but a full XSS review is still required.

## Layout

```
backend/
  api/            auth, users, policy, models_api, products, governance, ingest, query, audit
  auth/           passwords, sessions, deps (roles), ad (Kerberos + LDAP), providers (OIDC/SAML interface)
  policy/         catalog (AO controls), store (versioning)
  llm/            adapters, egress (gate + ceiling), prompt
  products/       claims (parser), marking_roll, workflow (release gate), export
  governance/     chain (hash-chained log)
  models/         marking, schema, governance (ORM)
  retrieval/      pdp, filters, filtered_search, vector_store
  db/migrations/  001 to 004 SQL
  cli.py          init-db, create-user, set-system-high, verify-chain
  serve.py        production launcher
  dev.py          development launcher
frontend/src/     App, api, marking, components/ (Login, PolicyPage, ModelsPage,
                  DraftWorkspace, ProductView, ProductList, UsersPage,
                  GovernancePage, IntakeForm, QueryInterface, MarkingPicker)
installer/        windows/ (build-bundle, install, uninstall), linux/ (build-bundle,
                  install, systemd units), common/roles.sql
tests/            v0.1 suites, test_release_gate.py, test_llm_units.py,
                  test_postgres_live.py, test_ad_kerberos.py
USER_MANUAL.md    end-user guide by role (PDF: python tools/build_manual_pdf.py USER_MANUAL.md USER_MANUAL.pdf)
```
