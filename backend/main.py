"""FastAPI application entry point.

Run with: uvicorn backend.main:app --reload
Apply backend/db/migrations/001_initial.sql to Postgres before first run.
"""

from fastapi import FastAPI

from backend.api.audit import router as audit_router
from backend.api.ingest import router as ingest_router
from backend.api.query import router as query_router

app = FastAPI(
    title="Classification-Aware RAG Marking Tool",
    description=(
        "Document intake with mandatory classification and portion markings, "
        "and chunking that enforces marking inheritance. Scaffolding only — "
        "access control logic requires independent security review before use "
        "with real classified content."
    ),
)

app.include_router(ingest_router)
app.include_router(query_router)
app.include_router(audit_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
