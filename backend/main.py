"""FastAPI application entry point.

Production launch: python -m backend.serve (reads the service environment
file written by the installer). Development: python -m backend.dev.
"""

import os

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from backend import config
from backend.api.audit import router as audit_router
from backend.api.auth import router as auth_router
from backend.api.governance import router as governance_router
from backend.api.ingest import router as ingest_router
from backend.api.models_api import router as models_router
from backend.api.policy import router as policy_router
from backend.api.products import router as products_router
from backend.api.query import router as query_router
from backend.api.users import router as users_router

_dev = config.dev_mode()

app = FastAPI(
    title="Classification-Aware RAG Marking Tool",
    version="0.2.0",
    description=(
        "Classification-aware retrieval with mandatory markings, claim-level citation "
        "enforcement, AI-assistance disclosure, and an AO-configurable release gate. "
        "Requires independent security review before use with real classified content."
    ),
    docs_url="/docs" if _dev else None,
    redoc_url=None,
    openapi_url="/openapi.json" if _dev else None,
)

_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
        "base-uri 'none'; form-action 'self'")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("Content-Security-Policy", _CSP)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cache-Control", "no-store")
    if request.url.scheme == "https":
        response.headers.setdefault("Strict-Transport-Security",
                                    "max-age=31536000; includeSubDomains")
    return response


for r in (auth_router, users_router, policy_router, models_router, products_router,
          governance_router, ingest_router, query_router, audit_router):
    app.include_router(r)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


_dist = config.frontend_dist()
if _dist and os.path.isdir(_dist):
    app.mount("/", StaticFiles(directory=_dist, html=True), name="ui")
