"""
backend/app/main.py – FastAPI application entry point (M4).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import CORS_ORIGINS
from app.database import init_db
from app.routers.claims import router as claims_router
from app.routers.documents import router as documents_router
from app.routers.sources import router_references, router_sources

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("CiteVerify API starting up — initialising database.")
        init_db()
        yield

    app = FastAPI(
        title="CiteVerify API",
        description=(
            "Scientific claim and citation verification system. "
            "⚠️ Output assists human reviewers — never a final academic judgment."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(documents_router)
    app.include_router(claims_router)
    app.include_router(router_sources)
    app.include_router(router_references)

    @app.get("/api/health", tags=["health"])
    def health():
        """
        Health-check endpoint.
        Returns 200 OK when the server is running.
        Always includes a disclaimer that output is not a final judgment.
        """
        return {
            "status": "ok",
            "disclaimer": (
                "CiteVerify assists human reviewers. "
                "Output is NOT a final academic judgment."
            ),
        }

    return app


app = create_app()
