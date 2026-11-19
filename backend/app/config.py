"""
app/config.py – application settings loaded from .env.

All tuneable values live here.  Never hard-code paths or secrets elsewhere.
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

    # Contact – used as mailto= for Crossref / OpenAlex / Unpaywall
    contact_email: str = "citeverify@example.com"

    # Database
    database_url: str = "sqlite+aiosqlite:///./data/citeverify.db"

    # Data directories (relative to repo root when running from there)
    upload_dir: Path = Path("data/uploads")
    sources_dir: Path = Path("data/sources")
    cache_dir: Path = Path("data/cache")

    # LLM provider (mock | http | bob)
    llm_provider: str = "mock"

    # Semantic Scholar optional key
    s2_api_key: str = ""


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
