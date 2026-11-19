"""
app/main.py – FastAPI application entry point.

Start with:
    cd citeverify
    uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000

Or from backend/:
    uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.router import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    logger.info("CiteVerify API starting up...")
    init_db()   # synchronous – fine in startup
    yield
    logger.info("CiteVerify API shutting down.")


app = FastAPI(
    title="CiteVerify API",
    description=(
        "Scientific claim and citation verification system. "
        "⚠️ RESEARCH ASSISTANT ONLY — not a final academic judgment."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS – allow the Next.js dev server (localhost:3000)
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
app.include_router(router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health", tags=["meta"])
async def health():
    """Health check endpoint. Returns 200 when the API is running."""
    return {"status": "ok", "service": "citeverify-api"}


@app.get("/", tags=["meta"])
async def root():
    return {
        "service": "CiteVerify API",
        "docs": "/docs",
        "health": "/health",
        "disclaimer": (
            "This is a research assistant. "
            "All outputs must be reviewed by qualified human reviewers."
        ),
    }
