"""
app/models.py – SQLAlchemy ORM models for CiteVerify.

Stores enough data to serve the REST API without re-running the pipeline.
JSON columns serialize the full Pydantic objects so the API can reconstruct
them without a re-parse.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------

class DocumentRecord(Base):
    """One uploaded document."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_type: Mapped[str] = mapped_column(String)       # pdf | docx | text
    original_filename: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending")
    # pending | processing | done | error
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    num_pages: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    claims: Mapped[list["ClaimRecord"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    references: Mapped[list["ReferenceRecord"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# Reference
# ---------------------------------------------------------------------------

class ReferenceRecord(Base):
    """A bibliographic reference extracted from a document."""

    __tablename__ = "references"

    id: Mapped[str] = mapped_column(String, primary_key=True)   # reference_id
    doc_id: Mapped[str] = mapped_column(String, ForeignKey("documents.id"))
    raw_text: Mapped[str] = mapped_column(Text)
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    authors: Mapped[list] = mapped_column(JSON, default=list)
    year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    doi: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    venue: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    parse_confidence: Mapped[float] = mapped_column(Float, default=0.0)

    document: Mapped["DocumentRecord"] = relationship(back_populates="references")
    verdicts: Mapped[list["VerdictRecord"]] = relationship(
        back_populates="reference", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# Claim
# ---------------------------------------------------------------------------

class ClaimRecord(Base):
    """A single checkable claim."""

    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String, primary_key=True)   # claim_id
    doc_id: Mapped[str] = mapped_column(String, ForeignKey("documents.id"))
    text: Mapped[str] = mapped_column(Text)
    page: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    section: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    citation_markers: Mapped[list] = mapped_column(JSON, default=list)
    reference_ids: Mapped[list] = mapped_column(JSON, default=list)
    claim_type: Mapped[str] = mapped_column(String, default="factual")
    numbers_mentioned: Mapped[list] = mapped_column(JSON, default=list)
    context_before: Mapped[str] = mapped_column(Text, default="")
    context_after: Mapped[str] = mapped_column(Text, default="")
    flags: Mapped[list] = mapped_column(JSON, default=list)

    document: Mapped["DocumentRecord"] = relationship(back_populates="claims")
    verdicts: Mapped[list["VerdictRecord"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )
    reviews: Mapped[list["ReviewRecord"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

class VerdictRecord(Base):
    """One verification verdict for a (claim, reference) pair."""

    __tablename__ = "verdicts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    claim_id: Mapped[str] = mapped_column(String, ForeignKey("claims.id"))
    reference_id: Mapped[str] = mapped_column(String, ForeignKey("references.id"))
    verdict: Mapped[str] = mapped_column(String)
    explanation: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    needs_human_review: Mapped[bool] = mapped_column(Boolean, default=False)
    # Store full Pydantic JSON for evidence, breakdown, source_trace
    evidence_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    confidence_breakdown_json: Mapped[dict] = mapped_column(JSON, default=dict)
    source_trace_json: Mapped[dict] = mapped_column(JSON, default=dict)
    flags: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    claim: Mapped["ClaimRecord"] = relationship(back_populates="verdicts")
    reference: Mapped["ReferenceRecord"] = relationship(back_populates="verdicts")


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------

class ReviewRecord(Base):
    """A human reviewer action on a verdict."""

    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(String, primary_key=True)   # review_id
    claim_id: Mapped[str] = mapped_column(String, ForeignKey("claims.id"))
    reference_id: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    new_verdict: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    comment: Mapped[str] = mapped_column(Text, default="")
    reviewer: Mapped[str] = mapped_column(String)
    timestamp: Mapped[str] = mapped_column(String)

    claim: Mapped["ClaimRecord"] = relationship(back_populates="reviews")
