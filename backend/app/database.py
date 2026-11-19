"""
backend/app/database.py – SQLAlchemy engine, session factory, and Base.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import DATABASE_URL

# connect_args only needed for SQLite (disable same-thread restriction)
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency: yields a DB session and closes it afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables (called at startup)."""
    # Import models so SQLAlchemy registers them before create_all
    import app.models  # noqa: F401
    Base.metadata.create_all(bind=engine)
