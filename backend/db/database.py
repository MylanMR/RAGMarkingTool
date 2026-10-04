"""Database session wiring.

DATABASE_URL defaults to a local Postgres for development. The engine is
created lazily so unit tests can override get_session without a Postgres
driver installed.
"""

import os
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg2://postgres:postgres@localhost:5432/rag_marking"
)

_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        connect_args = {}
        if DATABASE_URL.startswith("sqlite"):
            # Dev-only path (backend.dev): FastAPI serves sync endpoints from
            # a threadpool, so sqlite must allow cross-thread connections.
            connect_args["check_same_thread"] = False
        _engine = create_engine(DATABASE_URL, future=True, connect_args=connect_args)
    return _engine


def get_session():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(), autoflush=False, autocommit=False, future=True
        )
    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()
