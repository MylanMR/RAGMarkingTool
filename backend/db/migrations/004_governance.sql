-- Phase 7-10: identity, AO policy, model registry, AI-assisted products,
-- hash-chained governance log. Mirrors backend/models/governance.py.

CREATE TABLE IF NOT EXISTS users (
    id                   varchar(36) PRIMARY KEY,
    username             varchar(128) NOT NULL UNIQUE,
    display_name         text NOT NULL,
    auth_source          varchar(16) NOT NULL CHECK (auth_source IN ('local','ad','oidc','saml')),
    password_hash        text,
    roles                jsonb NOT NULL,
    clearance            varchar(8) NOT NULL CHECK (clearance IN ('U','C','S','TS','TS/SCI')),
    citizenship          varchar(3) NOT NULL,
    compartments         jsonb NOT NULL,
    need_to_know_groups  jsonb NOT NULL,
    active               boolean NOT NULL,
    failed_attempts      integer NOT NULL,
    locked_until         timestamptz,
    must_change_password boolean NOT NULL,
    created_at           timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    token_hash  varchar(64) PRIMARY KEY,
    user_id     varchar(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  timestamptz NOT NULL,
    last_seen   timestamptz NOT NULL,
    expires_at  timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS policy_versions (
    version        integer PRIMARY KEY,
    settings       jsonb NOT NULL,
    relaxed        jsonb NOT NULL,
    justification  text,
    changed_by     text NOT NULL,
    changed_at     timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS model_endpoints (
    id                  varchar(36) PRIMARY KEY,
    name                varchar(128) NOT NULL UNIQUE,
    adapter             varchar(32) NOT NULL,
    base_url            text NOT NULL,
    model_id            text NOT NULL,
    max_classification  varchar(8) NOT NULL CHECK (max_classification IN ('U','C','S','TS','TS/SCI')),
    credential_ref      text CHECK (credential_ref IS NULL OR credential_ref ~ '^(env|file):'),
    extra               jsonb NOT NULL,
    enabled             boolean NOT NULL,
    created_by          text NOT NULL,
    approved_by         text,
    approved_at         timestamptz,
    created_at          timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id                  varchar(36) PRIMARY KEY,
    title               text NOT NULL,
    question            text NOT NULL,
    author_id           varchar(36) NOT NULL REFERENCES users(id),
    state               varchar(16) NOT NULL CHECK (state IN ('draft','in_review','approved','released')),
    model_endpoint_id   varchar(36) NOT NULL,
    model_name          text NOT NULL,
    adapter             varchar(32) NOT NULL,
    model_id_requested  text NOT NULL,
    model_id_reported   text,
    model_ceiling       varchar(8) NOT NULL,
    prompt_sha256       varchar(64) NOT NULL,
    raw_output_sha256   varchar(64) NOT NULL,
    withheld_chunk_ids  jsonb NOT NULL,
    query_audit_id      varchar(36),
    policy_version      integer REFERENCES policy_versions(version),
    banner_classification varchar(8),
    banner_controls     jsonb,
    content_sha256      varchar(64),
    submitted_at        timestamptz,
    reviewer_id         varchar(36),
    reviewed_at         timestamptz,
    releaser_id         varchar(36),
    released_at         timestamptz,
    return_note         text,
    created_at          timestamptz NOT NULL,
    updated_at          timestamptz NOT NULL,
    -- Separation of duties enforced in the database as well as the app.
    CHECK (reviewer_id IS NULL OR reviewer_id <> author_id),
    CHECK (releaser_id IS NULL OR releaser_id <> author_id)
);
CREATE INDEX IF NOT EXISTS ix_products_state ON products (state);
CREATE INDEX IF NOT EXISTS ix_products_author ON products (author_id);

CREATE TABLE IF NOT EXISTS product_claims (
    id               varchar(36) PRIMARY KEY,
    product_id       varchar(36) NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    seq              integer NOT NULL,
    text             text NOT NULL,
    kind             varchar(16) NOT NULL CHECK (kind IN ('cited','uncited','judgment')),
    cited_sources    jsonb NOT NULL,
    invalid_refs     jsonb NOT NULL,
    derived_marking  text,
    portion_marking  text,
    classification   varchar(8),
    dissem_controls  jsonb,
    disposition      varchar(32),
    disposition_by   varchar(36),
    disposition_note text
);

CREATE TABLE IF NOT EXISTS product_sources (
    id              varchar(36) PRIMARY KEY,
    product_id      varchar(36) NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    num             integer NOT NULL,
    chunk_id        varchar(36) NOT NULL,
    parent_doc_id   varchar(36) NOT NULL,
    doc_title       text NOT NULL,
    source_system   text NOT NULL,
    portion_marking text NOT NULL,
    classification  varchar(8) NOT NULL,
    dissem_controls jsonb NOT NULL,
    program         text
);

CREATE TABLE IF NOT EXISTS governance_events (
    seq           serial PRIMARY KEY,
    ts            timestamptz NOT NULL,
    actor         text NOT NULL,
    event_type    varchar(64) NOT NULL,
    subject_type  varchar(32) NOT NULL,
    subject_id    varchar(64) NOT NULL,
    payload       jsonb NOT NULL,
    prev_hash     varchar(64) NOT NULL,
    hash          varchar(64) NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_gov_type ON governance_events (event_type);
CREATE INDEX IF NOT EXISTS ix_gov_subject ON governance_events (subject_id);

-- Append-only: the application role may insert and read, never rewrite.
CREATE OR REPLACE FUNCTION governance_events_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'governance_events is append-only';
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_governance_immutable ON governance_events;
CREATE TRIGGER trg_governance_immutable BEFORE UPDATE OR DELETE ON governance_events
    FOR EACH ROW EXECUTE FUNCTION governance_events_immutable();
