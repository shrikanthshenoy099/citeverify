"""
backend/app/config.py – Application-wide settings loaded from environment.
All secrets and tuneable values come from .env (via python-dotenv).
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parents[2]          # project root
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", str(BASE_DIR / "data" / "uploads")))
SOURCES_DIR = Path(os.environ.get("SOURCES_DIR", str(BASE_DIR / "data" / "sources")))
CACHE_DIR = Path(os.environ.get("CACHE_DIR", str(BASE_DIR / "data" / "cache")))

for _d in (UPLOAD_DIR, SOURCES_DIR, CACHE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ── Database ─────────────────────────────────────────────────────────────────
DATABASE_URL: str = os.environ.get(
    "DATABASE_URL", f"sqlite:///{BASE_DIR / 'data' / 'citeverify.db'}"
)

# ── Contact (Crossref / OpenAlex mailto) ─────────────────────────────────────
CONTACT_EMAIL: str = os.environ.get("CONTACT_EMAIL", "citeverify@example.com")

# ── LLM ──────────────────────────────────────────────────────────────────────
LLM_PROVIDER: str = os.environ.get("LLM_PROVIDER", "mock")

# ── File size limit (bytes) ───────────────────────────────────────────────────
MAX_UPLOAD_BYTES: int = int(os.environ.get("MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))  # 50 MB

# ── CORS origins (comma-separated) ───────────────────────────────────────────
CORS_ORIGINS: list[str] = [
    o.strip()
    for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]
