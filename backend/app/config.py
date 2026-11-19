"""
app/config.py – Application-wide settings loaded from environment / .env.

All tuneable thresholds live here so they are easy to adjust without touching
business logic.
"""

from __future__ import annotations

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── LLM ──────────────────────────────────────────────────────────────────
    llm_provider: str = "mock"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    use_mocks: bool = True

    # ── Contact / API keys ───────────────────────────────────────────────────
    contact_email: str = "citeverify@example.com"
    s2_api_key: str = ""

    # ── Paths ────────────────────────────────────────────────────────────────
    data_dir: Path = Path("./data")
    uploads_dir: Path = Path("./data/uploads")
    sources_dir: Path = Path("./data/sources")
    cache_dir: Path = Path("./data/cache")

    # ── Embedding ────────────────────────────────────────────────────────────
    embedding_model: str = "all-MiniLM-L6-v2"

    # ── Chunking ─────────────────────────────────────────────────────────────
    chunk_words: int = 250
    chunk_overlap_words: int = 50

    # ── Matching thresholds ──────────────────────────────────────────────────
    # Title match: rapidfuzz ratio >= title_match_threshold AND
    #   (first-author surname matches OR year within year_tolerance) → matched.
    # If ratio >= title_match_strict, accept even without author/year.
    title_match_threshold: float = 85.0
    title_match_strict: float = 92.0
    year_tolerance: int = 1

    # Cosine similarity below this → flag "low_retrieval_score"
    low_retrieval_threshold: float = 0.35

    # Fuzzy quote-match ratio for locate_quote
    quote_match_threshold: float = 90.0

    # ── Confidence weights (must sum to 1.0) ─────────────────────────────────
    weight_retrieval: float = 0.20
    weight_llm_certainty: float = 0.30
    weight_text_match: float = 0.20
    weight_full_text: float = 0.10
    weight_numeric_match: float = 0.20

    # full_text component scores per text_level
    full_text_score_full: float = 1.0
    full_text_score_ocr: float = 0.7      # full_text but with ocr_text flag
    full_text_score_abstract: float = 0.4
    full_text_score_metadata: float = 0.2
    full_text_score_none: float = 0.0

    # Confidence below this → needs_human_review = True
    human_review_confidence_threshold: float = 0.60

    # abstract_only sources: cap confidence at this value
    abstract_only_confidence_cap: float = 0.50

    # Source older than this many years AND time-sensitive → "possibly_outdated"
    outdated_years_threshold: int = 10

    # ── File upload limits ───────────────────────────────────────────────────
    max_upload_bytes: int = 50 * 1024 * 1024   # 50 MB


# Singleton – import this everywhere
settings = Settings()
from functools import lru_cache

@lru_cache
def get_settings():
       return settings