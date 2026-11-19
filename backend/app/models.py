"""
backend/app/models.py – SQLAlchemy ORM models.

Stores the pipeline state so the app survives restarts and supports
async status polling.  JSON columns hold the serialised Pydantic objects.
"""

from __future__ import annotations

import datetime
import json
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


# ---------------------------------------------------------------------------
# DocumentRecord
# ---------------------------------------------------------------------------

class DocumentRecord(Base):
    """One uploaded document (PDF, DOCX, or pasted text)."""

    __tablename__ = "documents"

    doc_id: Mapped[str] = mapped_column(String, primary_key=True)
    source_type: Mapped[str] = mapped_column(String)          # pdf|docx|text
    original_filename: Mapped[str | None] = mapped_column(String, nullable=True)
    file_path: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(
        String, default="pending"
    )  # pending|processing|done|error
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    num_pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warnings: Mapped[Any] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    claims: Mapped[list["ClaimRecord"]] = relationship(
        "ClaimRecord", back_populates="document", cascade="all, delete-orphan"
    )
    references: Mapped[list["ReferenceRecord"]] = relationship(
        "ReferenceRecord", back_populates="document", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# ReferenceRecord
# ---------------------------------------------------------------------------

class ReferenceRecord(Base):
    """One bibliographic reference extracted from a document."""

    __tablename__ = "references"

    reference_id: Mapped[str] = mapped_column(String, primary_key=True)
    doc_id: Mapped[str] = mapped_column(String, ForeignKey("documents.doc_id"))
    raw_text: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    authors: Mapped[Any] = mapped_column(JSON, default=list)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    doi: Mapped[str | None] = mapped_column(String, nullable=True)
    venue: Mapped[str | None] = mapped_column(String, nullable=True)
    parse_confidence: Mapped[float] = mapped_column(Float, default=0.0)

    # Retrieved source (flattened for quick querying)
    matched: Mapped[bool] = mapped_column(Integer, default=False)
    source_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    source_pdf_path: Mapped[str | None] = mapped_column(String, nullable=True)
    text_level: Mapped[str] = mapped_column(String, default="none")
    source_flags: Mapped[Any] = mapped_column(JSON, default=list)
    source_json: Mapped[Any] = mapped_column(JSON, nullable=True)  # full Source dict

    document: Mapped["DocumentRecord"] = relationship(
        "DocumentRecord", back_populates="references"
    )
    verdicts: Mapped[list["VerdictRecord"]] = relationship(
        "VerdictRecord", back_populates="reference", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# ClaimRecord
# ---------------------------------------------------------------------------

class ClaimRecord(Base):
    """One claim extracted from a document."""

    __tablename__ = "claims"

    claim_id: Mapped[str] = mapped_column(String, primary_key=True)
    doc_id: Mapped[str] = mapped_column(String, ForeignKey("documents.doc_id"))
    text: Mapped[str] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section: Mapped[str | None] = mapped_column(String, nullable=True)
    char_start: Mapped[int] = mapped_column(Integer, default=0)
    char_end: Mapped[int] = mapped_column(Integer, default=0)
    claim_type: Mapped[str] = mapped_column(String, default="factual")
    citation_markers: Mapped[Any] = mapped_column(JSON, default=list)
    reference_ids: Mapped[Any] = mapped_column(JSON, default=list)
    numbers_mentioned: Mapped[Any] = mapped_column(JSON, default=list)
    context_before: Mapped[str] = mapped_column(Text, default="")
    context_after: Mapped[str] = mapped_column(Text, default="")
    flags: Mapped[Any] = mapped_column(JSON, default=list)

    document: Mapped["DocumentRecord"] = relationship(
        "DocumentRecord", back_populates="claims"
    )
    verdicts: Mapped[list["VerdictRecord"]] = relationship(
        "VerdictRecord", back_populates="claim", cascade="all, delete-orphan"
    )
    reviews: Mapped[list["ReviewRecord"]] = relationship(
        "ReviewRecord", back_populates="claim", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# VerdictRecord
# ---------------------------------------------------------------------------

class VerdictRecord(Base):
    """One verdict for a (claim, reference) pair."""

    __tablename__ = "verdicts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    claim_id: Mapped[str] = mapped_column(String, ForeignKey("claims.claim_id"))
    reference_id: Mapped[str] = mapped_column(String, ForeignKey("references.reference_id"))
    verdict: Mapped[str] = mapped_column(String)
    explanation: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    needs_human_review: Mapped[bool] = mapped_column(Integer, default=False)
    flags: Mapped[Any] = mapped_column(JSON, default=list)
    verdict_json: Mapped[Any] = mapped_column(JSON, nullable=True)  # full Verdict dict
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )

    claim: Mapped["ClaimRecord"] = relationship("ClaimRecord", back_populates="verdicts")
    reference: Mapped["ReferenceRecord"] = relationship(
        "ReferenceRecord", back_populates="verdicts"
    )


# ---------------------------------------------------------------------------
# ReviewRecord
# ---------------------------------------------------------------------------

class ReviewRecord(Base):
    """Human review action on a (claim, reference) verdict."""

    __tablename__ = "reviews"

    review_id: Mapped[str] = mapped_column(String, primary_key=True)
    claim_id: Mapped[str] = mapped_column(String, ForeignKey("claims.claim_id"))
    reference_id: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)       # accept|reject|comment|override
    new_verdict: Mapped[str | None] = mapped_column(String, nullable=True)
    comment: Mapped[str] = mapped_column(Text, default="")
    reviewer: Mapped[str] = mapped_column(String)
    timestamp: Mapped[str] = mapped_column(String)    # ISO-8601

    claim: Mapped["ClaimRecord"] = relationship("ClaimRecord", back_populates="reviews")
