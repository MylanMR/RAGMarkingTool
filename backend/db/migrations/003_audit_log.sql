-- 003_audit_log.sql — queryable query audit log (Postgres)
-- One row per query attempt, including rejected and failed ones. Scalar
-- columns for common filters, jsonb for full fidelity.

BEGIN;

CREATE TABLE query_audit_log (
    id              uuid PRIMARY KEY,
    ts              timestamptz NOT NULL,
    user_id         text NOT NULL,
    clearance       varchar(8),
    citizenship     varchar(3),
    outcome         varchar(32) NOT NULL
                    CHECK (outcome IN ('ok','integrity_failure','rejected_attributes')),
    query_text      text NOT NULL,
    top_k           integer,
    result_count    integer NOT NULL,
    user_attributes jsonb NOT NULL,
    filter_summary  jsonb,
    returned_chunks jsonb,
    decisions       jsonb,
    detail          text
);

CREATE INDEX idx_audit_ts ON query_audit_log (ts DESC);
CREATE INDEX idx_audit_user ON query_audit_log (user_id, ts DESC);
CREATE INDEX idx_audit_outcome ON query_audit_log (outcome, ts DESC);
CREATE INDEX idx_audit_returned_chunks ON query_audit_log USING gin (returned_chunks);

COMMIT;
