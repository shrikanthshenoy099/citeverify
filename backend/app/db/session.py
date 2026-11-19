"""
app/db/session.py – SQLAlchemy session / engine factory.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.config import settings
from app.db.models import Base


def _get_db_path() -> Path:
    db_path = settings.data_dir / "citeverify.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


engine = create_engine(
    f"sqlite:///{_get_db_path()}",
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Create all tables (idempotent)."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency that yields a DB session."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
