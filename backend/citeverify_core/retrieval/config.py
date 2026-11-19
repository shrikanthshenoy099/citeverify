"""
M2 – Source Retrieval module configuration.
All thresholds and defaults live here so they can be tuned without touching logic.
"""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths (resolved relative to this file's package root)
# ---------------------------------------------------------------------------
_BASE = Path(__file__).parent.parent.parent.parent  # citeverify/
DATA_DIR = _BASE / "data"
SOURCES_DIR = DATA_DIR / "sources"
INDEX_DIR = DATA_DIR / "cache" / "index"
UPLOADS_DIR = DATA_DIR / "uploads"
MOCK_DIR = DATA_DIR / "mock"

# ---------------------------------------------------------------------------
# Embedding model
# ---------------------------------------------------------------------------
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------
CHUNK_WORDS: int = int(os.getenv("CHUNK_WORDS", "250"))
CHUNK_OVERLAP_WORDS: int = int(os.getenv("CHUNK_OVERLAP_WORDS", "50"))

# ---------------------------------------------------------------------------
# Retrieval / similarity
# ---------------------------------------------------------------------------
TOP_K: int = int(os.getenv("TOP_K", "5"))
LOW_RETRIEVAL_THRESHOLD: float = float(os.getenv("LOW_RETRIEVAL_THRESHOLD", "0.35"))

# ---------------------------------------------------------------------------
# Title / author / year matching
# ---------------------------------------------------------------------------
TITLE_RATIO_MATCHED: float = float(os.getenv("TITLE_RATIO_MATCHED", "85"))
TITLE_RATIO_SOLO: float = float(os.getenv("TITLE_RATIO_SOLO", "92"))  # accept without author/year
YEAR_TOLERANCE: int = int(os.getenv("YEAR_TOLERANCE", "1"))

# ---------------------------------------------------------------------------
# Quote location (fuzzy)
# ---------------------------------------------------------------------------
QUOTE_FUZZY_THRESHOLD: float = float(os.getenv("QUOTE_FUZZY_THRESHOLD", "90"))

# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
HTTP_TIMEOUT: int = int(os.getenv("HTTP_TIMEOUT", "20"))
HTTP_MAX_RETRIES: int = int(os.getenv("HTTP_MAX_RETRIES", "3"))
HTTP_BACKOFF_FACTOR: float = float(os.getenv("HTTP_BACKOFF_FACTOR", "1.5"))

# ---------------------------------------------------------------------------
# API contacts / keys
# ---------------------------------------------------------------------------
CONTACT_EMAIL: str = os.getenv("CONTACT_EMAIL", "citeverify@example.com")
S2_API_KEY: str | None = os.getenv("S2_API_KEY")  # optional

# ---------------------------------------------------------------------------
# Concurrency / download limits
# ---------------------------------------------------------------------------
# Maximum number of worker threads for parallel retrieval (not yet wired; reserved for M4).
MAX_WORKERS: int = int(os.getenv("MAX_WORKERS", "4"))
# Maximum PDF size in bytes to download (default 50 MB)
PDF_MAX_BYTES: int = int(os.getenv("PDF_MAX_BYTES", str(50 * 1024 * 1024)))

# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------
OCR_DPI: int = int(os.getenv("OCR_DPI", "200"))
