-- Least-privilege database roles, applied by both installers after
-- migrations. ragmt_owner owns the schema and runs migrations; the service
-- connects as ragmt_app, which can never rewrite audit or governance history.
-- The installer creates the ragmt_app login role as the superuser first
-- (ragmt_owner deliberately lacks CREATEROLE); this file runs as
-- ragmt_owner, which owns the tables and so can grant on them.

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO ragmt_app;

GRANT SELECT, INSERT, UPDATE, DELETE ON
  documents, sections, chunks, users, auth_sessions, model_endpoints,
  products, product_claims, product_sources
TO ragmt_app;
GRANT SELECT, INSERT ON policy_versions TO ragmt_app;

-- Append-only for the service account.
GRANT SELECT, INSERT ON query_audit_log, governance_events TO ragmt_app;
GRANT USAGE, SELECT ON SEQUENCE governance_events_seq_seq TO ragmt_app;
