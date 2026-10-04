-- 002_pgvector.sql — embedding storage (Postgres + pgvector)
-- The embedding lives on the chunks row itself so the vector can never be
-- separated from its marking metadata, and marking filters are ordinary
-- WHERE clauses evaluated inside the similarity query.

BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE chunks ADD COLUMN embedding vector(384);

-- HNSW index for cosine distance. Note: Postgres can only use this index
-- when the marking predicates are applied in the same query, which is the
-- required pattern anyway (query-level filtering, never post-retrieval).
CREATE INDEX idx_chunks_embedding ON chunks
    USING hnsw (embedding vector_cosine_ops);

COMMIT;
