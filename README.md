# Classification-Aware RAG Marking Tool

Document intake, marking, and retrieval-filtering scaffolding for a
classification-aware RAG pipeline. Markings are applied at intake, inherited by
every chunk at creation time, and (in later phases) enforced at query time by a
policy decision point.

> **Scaffolding only.** Access control logic requires independent security
> review before use with real classified content. See the review checkpoints in
> the project spec.

## Status

| Phase | Scope | Status |
|---|---|---|
| 1 | Intake API + Postgres marking schema | ✅ Built |
| 2 | Chunker with enforced marking inheritance | ✅ Built |
| 3 | Embedding + vector store with query-level marking filters | ✅ Built |
| 4 | Policy decision point + filtered retrieval | ✅ Built — **requires independent security review before real data** |
| 5 | Queryable audit logging | ✅ Built |
| 6 | Integration tests across phases | Partial — partial-access users × mixed-classification corpus covered in `test_query_api.py` |
| — | React frontend (intake, section marking, query) | ✅ Built and verified end to end against the dev backend |

## Core invariant: no silent defaults

No code path assigns a default classification. This is enforced at four layers:

1. **API** — `portion_marking` and banner `classification` are required Pydantic
   fields; requests without them fail with 422.
2. **Domain** — `PortionMarking.parse` raises `MarkingError` on missing,
   malformed, or contradictory markings (e.g. `NOFORN` + `REL TO`).
3. **Chunker** — validates every section's marking *before* emitting any chunk,
   so a bad section can never leave partially chunked output; chunks never span
   section (marking) boundaries.
4. **Database** — all classification columns are `NOT NULL` with no default,
   plus `CHECK` constraints on the allowed levels
   (`backend/db/migrations/001_initial.sql`).
5. **Vector store** — an embedding cannot be upserted without a valid marking,
   `search` requires a `ChunkFilter` (there is no unfiltered search method),
   and filters are deny-by-default in every dimension: empty `allowed_levels`
   matches nothing, a chunk's dissem controls must be a *subset* of the
   permitted set, and program-marked chunks are excluded unless the program is
   explicitly allowed.

The banner classification must dominate (be ≥) the highest section level.

## Phase 5: queryable audit logging

Every query attempt writes one row to `query_audit_log` (migration
`003_audit_log.sql`): timestamp, user, the full attribute set evaluated, the
filter applied, the markings on every chunk returned, and the per-hit PDP
decision reasons. Failures are logged too — `rejected_attributes` and
`integrity_failure` rows carry the reason in `detail`.

- **Fail-closed auditing:** the audit row is committed in the same request,
  before the response is returned. If the row cannot be persisted, the result
  is never served.
- **Queryable, not append-only text:** `GET /audit/queries` filters by
  `user_id`, `outcome`, `since`/`until` with pagination;
  `GET /audit/queries/{id}` returns the full entry. Scalar columns are
  indexed for the common filters; jsonb keeps full fidelity (with a GIN index
  on returned chunks for "who saw this chunk" queries in Postgres).
- **The log itself is sensitive** (query text, attributes, markings).
  Production must restrict `/audit` to an auditor role — part of the access
  control walkthrough before connecting a production IdP.

## Phase 4: policy decision point + filtered retrieval

`backend/retrieval/pdp.py` is isolated (imports only the marking domain model
and the filter type — no DB, no framework, no I/O) so it can be reviewed and
tested independently. `decide(user, marking)` returns allow/deny and **every
decision carries a reason string** for logging.

Retrieval flow (`backend/retrieval/filtered_search.py`, `POST /query`):

1. The retrieval layer asks the store for the distinct dissemination controls
   it currently holds and has the PDP rule on each one, composing the
   `ChunkFilter`. The filter is therefore made of PDP decisions — there is no
   second copy of the policy. The property test
   `test_filter_matches_iff_pdp_allows` asserts `build_filter` is *exactly* as
   permissive as `decide` across a users × markings matrix.
2. The store enforces that filter inside the similarity query (Phase 3).
3. Defense in depth: every returned hit is re-verified against `decide()`. If
   the store and PDP ever disagree, the query fails closed with
   `RetrievalIntegrityError` — nothing is returned.

Placeholder policy semantics, **flagged for the independent security review**
required by the spec before any real data is connected:

- **Auth is scaffolding-only:** `POST /query` accepts user attributes in the
  request body. Production must derive them from the authenticated identity
  (PKI/IdP middleware) — never from the client.
- ORCON is modeled as membership in the need-to-know group `"ORCON"`.
- Citizenship is a single trigraph; dual nationality is not modeled.
- Unknown dissemination controls are denied by default.
- The pgvector SQL search path still needs exercising against a live
  Postgres+pgvector instance (in-memory store carries the test coverage).

## Phase 3: embedding + filtered vector search

- `POST /ingest/documents/{doc_id}/embed` embeds a document's chunks and
  upserts them (idempotent, keyed by `chunk_id`).
- **pgvector path (production):** migration `002_pgvector.sql` puts the
  `embedding` column on the `chunks` row itself, so the vector can never be
  separated from its marking metadata; `PgVectorStore.search` applies the
  marking filter in the SQL `WHERE` clause of the similarity query.
- **In-memory path (tests/dev):** `InMemoryVectorStore` implements identical
  semantics — candidates are filtered *before* ranking. The test
  `test_filter_is_not_post_retrieval_truncation` proves filtering is not
  top-k truncation: when the nearest neighbors are all `S//NOFORN`, a U-only
  filter still returns the full top-k of U chunks.
- `HashingEmbedder` is a deterministic, dependency-free dev stand-in; swap in
  a real embedding model behind the same `Embedder` protocol for production.
  The pgvector search path has no unit-test coverage here (needs a live
  Postgres with the extension) — exercise it during the Phase 4 checkpoint.

## Frontend

Vite + React app in `frontend/` with the spec's three components:

- **IntakeForm** — document intake with banner classification and per-section
  markings. Submission is blocked (client-side) while any section is unmarked
  or the banner doesn't dominate the highest section level; the backend
  re-validates both regardless. After ingest, a button embeds the chunks.
- **SectionMarker** — per-section marking builder: classification select that
  starts empty (no default), NOFORN/ORCON checkboxes, REL TO country list.
  It mirrors backend rules in the UX (U carries no controls, NOFORN and
  REL TO are mutually exclusive) and shows the composed portion marking as a
  color-coded chip (U green, C blue, S red, TS orange).
- **QueryInterface** — user attributes + query; results render with
  classification banners, the applied filter summary, per-hit PDP decision
  reasons, and the audit entry id. The attribute form is scaffolding-only
  auth, labeled as such in the UI.

Run it (requires Node.js ≥ 18):

```bash
cd frontend
npm install
npm run dev   # http://localhost:5173, proxies API calls to :8000
```

### Dev backend without Postgres

`backend/dev.py` runs the API against sqlite (`dev.db`) with an in-process
vector store, so the whole stack works locally with no Postgres:

```bash
.venv/bin/python -m backend.dev   # http://localhost:8000
```

Dev-only caveats: embeddings live in process memory (re-run the embed step
after a restart), and `VECTOR_STORE=memory` selects the in-memory store —
production uses the pgvector path and the SQL migrations.

## Layout

```
backend/
  api/ingest.py               POST /ingest/documents, POST .../{id}/embed
  chunking/marked_chunker.py  marking-inheriting chunker
  embedding/embedder.py       Embedder protocol + deterministic dev embedder
  embedding/pipeline.py       embed a document's chunks into the vector store
  models/marking.py           levels, dissem controls, portion-marking parser
  models/schema.py            SQLAlchemy ORM (documents, sections, chunks)
  db/database.py              engine/session wiring (DATABASE_URL)
  db/migrations/               001 marking schema, 002 pgvector embedding
  api/query.py                POST /query — PDP-filtered retrieval, audited
  api/audit.py                GET /audit/queries — queryable audit log
  audit/recorder.py           writes one audit row per query attempt
  retrieval/filters.py        ChunkFilter — deny-by-default marking filter
  retrieval/pdp.py            policy decision point (isolated, no I/O)
  retrieval/filtered_search.py PDP-built filter + fail-closed hit verification
  retrieval/vector_store.py   PgVectorStore (prod) + InMemoryVectorStore (test)
tests/
  test_marking.py                  parser and validation rules
  test_marking_inheritance.py      chunker invariants
  test_ingest_api.py               end-to-end intake against in-memory sqlite
  test_vector_store_filtering.py   query-level filter semantics
  test_embedding_pipeline.py       ingest -> embed -> filtered search
  test_pdp_filtering.py            PDP matrix + filter/PDP consistency property
  test_query_api.py                partial-access users vs mixed corpus
  test_audit_log.py                audit recording + audit API queryability
frontend/
  src/App.jsx                      tabs: intake / query
  src/marking.js                   marking composition + level colors
  src/api.js                       fetch wrapper for the backend API
  src/components/IntakeForm.jsx    document intake + embed
  src/components/SectionMarker.jsx per-section marking builder
  src/components/QueryInterface.jsx attribute form + marked results
```

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Run tests (no database needed — API tests use in-memory sqlite):

```bash
.venv/bin/python -m pytest
```

Run the API against Postgres:

```bash
createdb rag_marking
psql rag_marking -f backend/db/migrations/001_initial.sql
psql rag_marking -f backend/db/migrations/002_pgvector.sql   # requires pgvector
psql rag_marking -f backend/db/migrations/003_audit_log.sql
export DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/rag_marking
.venv/bin/uvicorn backend.main:app --reload
```

Example request:

```bash
curl -s -X POST http://localhost:8000/ingest/documents \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "Quarterly Threat Assessment",
    "source_system": "intake-ui",
    "classification": "S",
    "dissem_controls": ["NOFORN"],
    "sections": [
      {"heading": "Overview", "content": "Unclassified overview.", "portion_marking": "(U)"},
      {"heading": "Findings", "content": "Secret findings.", "portion_marking": "(S//NF)"}
    ]
  }'
```

## Marking format

Portion markings follow `(LEVEL)` or `(LEVEL//CTRL[/CTRL...])`:

- Levels: `U`, `C`, `S`, `TS`
- Controls: `NF`/`NOFORN`, `OC`/`ORCON`, `REL TO CCC[, CCC...]`
- Rejected: unknown levels or controls, `NOFORN` combined with `REL TO`,
  multiple `REL TO` statements, controls on `U` portions.

Controls are canonicalized on ingest (`NF` → `NOFORN`), so stored markings are
uniform for later PDP filtering.

## Next steps (Phase 6+)

- Install Node.js, `npm install` in `frontend/`, and exercise the UI against
  the running backend (it has not been run yet).
- Round out integration coverage against live Postgres + pgvector (the SQL
  search path and jsonb subset filtering have no automated coverage here).
- **Checkpoint (spec §7): independent security review of the PDP before any
  integration with real data**, and a full access-control walkthrough before
  connecting a production IdP or PKI system.
