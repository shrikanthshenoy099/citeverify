"""
app/database.py – SQLAlchemy sync engine + session factory + Base.

Uses a synchronous engine on a thread-pool for FastAPI integration.
Avoids the greenlet dependency that SQLAlchemy[asyncio] requires.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


_engine = None
_SessionFactory = None


def _make_url(raw: str) -> str:
    """Convert an aiosqlite URL to a plain sqlite URL for sync usage."""
    return re.sub(r"sqlite\+aiosqlite", "sqlite", raw)


def _get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        raw_url = settings.database_url
        url = _make_url(raw_url)

        # Ensure data directory exists for file-based SQLite
        path_match = re.search(r"sqlite:///(.+)", url)
        if path_match:
            db_path = Path(path_match.group(1))
            db_path.parent.mkdir(parents=True, exist_ok=True)

        _engine = create_engine(url, connect_args={"check_same_thread": False}, echo=False)

        # Enable WAL mode for better concurrency
        @event.listens_for(_engine, "connect")
        def _set_wal(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA journal_mode=WAL")

        logger.info("Database engine created: %s", url)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=_get_engine(), autoflush=False, autocommit=False)
    return _SessionFactory


@contextmanager
def get_db_context() -> Generator[Session, None, None]:
    """Context manager that yields a Session and handles commit/rollback."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a Session."""
    with get_db_context() as session:
        yield session


def init_db() -> None:
    """Create all tables (called once at startup)."""
    engine = _get_engine()
    Base.metadata.create_all(engine)
    logger.info("Database tables created/verified.")
