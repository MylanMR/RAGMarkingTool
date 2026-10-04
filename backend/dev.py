"""Development launcher: sqlite DB + in-memory vector store, no Postgres needed.

Usage: .venv/bin/python -m backend.dev  (from the project root)

Documents, chunks, and audit rows persist in dev.db; embeddings live in
process memory and vanish on restart — re-run the embed step afterwards.
Production uses Postgres + pgvector via the migrations in backend/db/.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./dev.db")
os.environ.setdefault("VECTOR_STORE", "memory")
os.environ.setdefault("RAGMT_DEV", "1")


def main() -> None:
    from backend.db.database import get_engine
    from backend.models import governance  # noqa: F401
    from backend.models import schema

    schema.Base.metadata.create_all(get_engine())

    import uvicorn

    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
