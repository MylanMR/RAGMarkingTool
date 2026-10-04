-- 001_initial.sql — marking metadata schema (Postgres)
-- Every classification column is NOT NULL with NO DEFAULT, enforced at the
-- database layer so no code path can create an unmarked row.

BEGIN;

CREATE TABLE documents (
    id              uuid PRIMARY KEY,
    title           text NOT NULL,
    source_system   text NOT NULL,
    classification  varchar(8) NOT NULL CHECK (classification IN ('U','C','S','TS','TS/SCI')),
    dissem_controls jsonb NOT NULL,
    program         text,
    content_hash    varchar(64) NOT NULL,
    ingest_date     timestamptz NOT NULL
);

CREATE TABLE sections (
    id              uuid PRIMARY KEY,
    document_id     uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    seq             integer NOT NULL,
    heading         text,
    content         text NOT NULL,
    classification  varchar(8) NOT NULL CHECK (classification IN ('U','C','S','TS','TS/SCI')),
    portion_marking text NOT NULL CHECK (length(trim(portion_marking)) > 0),
    dissem_controls jsonb NOT NULL,
    program         text,
    UNIQUE (document_id, seq)
);

CREATE TABLE chunks (
    chunk_id        uuid PRIMARY KEY,
    parent_doc_id   uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    section_id      uuid NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
    seq             integer NOT NULL,
    content         text NOT NULL,
    classification  varchar(8) NOT NULL CHECK (classification IN ('U','C','S','TS','TS/SCI')),
    portion_marking text NOT NULL CHECK (length(trim(portion_marking)) > 0),
    dissem_controls jsonb NOT NULL,
    program         text,
    source_system   text NOT NULL,
    ingest_date     timestamptz NOT NULL,
    content_hash    varchar(64) NOT NULL,
    UNIQUE (parent_doc_id, seq)
);

CREATE INDEX idx_chunks_parent_doc ON chunks (parent_doc_id);
CREATE INDEX idx_chunks_classification ON chunks (classification);
CREATE INDEX idx_chunks_dissem_controls ON chunks USING gin (dissem_controls);

COMMIT;
