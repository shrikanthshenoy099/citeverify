"""
app/main.py – FastAPI application entry point.

Owner: M4 (Product & Integration).
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db.session import init_db
from app.routers.documents import router as documents_router
from app.routers.claims import router as claims_router
from app.routers.sources import router_sources, router_references

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("CiteVerify starting up – initialising database …")
    init_db()
    # Ensure data directories exist
    from app.config import settings
    for d in (settings.uploads_dir, settings.sources_dir, settings.cache_dir):
        d.mkdir(parents=True, exist_ok=True)
    logger.info("Startup complete.")
    yield
    logger.info("CiteVerify shutting down.")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="CiteVerify API",
    description=(
        "Scientific claim and citation verification system. "
        "⚠ All results are intended to ASSIST human reviewers and must not "
        "be treated as final academic judgments."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# CORS – allow the Next.js dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(documents_router)
app.include_router(claims_router)
app.include_router(router_sources)
app.include_router(router_references)


# ---------------------------------------------------------------------------
# Root health check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["health"])
def health():
    return {"status": "ok", "service": "citeverify"}
