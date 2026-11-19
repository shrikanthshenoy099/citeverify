"""
app/db/models.py – SQLAlchemy ORM models for SQLite.

Tables:
  document     – uploaded document metadata + status
  claim        – extracted claims (JSON payload)
  reference    – bibliographic references (JSON payload)
  source       – retrieval results (JSON payload)
  verdict      – per-(claim, reference) verification result (JSON payload)
  review       – human reviewer actions
"""

from __future__ import annotations

import datetime
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class DocumentRow(Base):
    __tablename__ = "document"

    doc_id = Column(String, primary_key=True)
    filename = Column(String, nullable=True)
    source_type = Column(String, nullable=False)   # "pdf" | "docx" | "text"
    status = Column(String, nullable=False, default="pending")
    # pending | parsing | retrieving | verifying | done | error
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    claims = relationship("ClaimRow", back_populates="document", cascade="all, delete-orphan")
    references = relationship("ReferenceRow", back_populates="document", cascade="all, delete-orphan")


class ClaimRow(Base):
    __tablename__ = "claim"

    claim_id = Column(String, primary_key=True)
    doc_id = Column(String, ForeignKey("document.doc_id"), nullable=False)
    payload = Column(Text, nullable=False)   # JSON-serialised Claim schema

    document = relationship("DocumentRow", back_populates="claims")
    verdicts = relationship("VerdictRow", back_populates="claim", cascade="all, delete-orphan")


class ReferenceRow(Base):
    __tablename__ = "reference"

    reference_id = Column(String, primary_key=True)
    doc_id = Column(String, ForeignKey("document.doc_id"), nullable=False)
    payload = Column(Text, nullable=False)   # JSON-serialised Reference schema

    document = relationship("DocumentRow", back_populates="references")
    source = relationship("SourceRow", back_populates="reference", uselist=False, cascade="all, delete-orphan")


class SourceRow(Base):
    __tablename__ = "source"

    reference_id = Column(String, ForeignKey("reference.reference_id"), primary_key=True)
    payload = Column(Text, nullable=False)   # JSON-serialised Source schema

    reference = relationship("ReferenceRow", back_populates="source")


class VerdictRow(Base):
    __tablename__ = "verdict"

    id = Column(Integer, primary_key=True, autoincrement=True)
    claim_id = Column(String, ForeignKey("claim.claim_id"), nullable=False)
    reference_id = Column(String, nullable=False)
    payload = Column(Text, nullable=False)   # JSON-serialised Verdict schema

    claim = relationship("ClaimRow", back_populates="verdicts")
    reviews = relationship("ReviewRow", back_populates="verdict", cascade="all, delete-orphan")


class ReviewRow(Base):
    __tablename__ = "review"

    review_id = Column(String, primary_key=True)
    claim_id = Column(String, ForeignKey("verdict.claim_id"), nullable=False)
    reference_id = Column(String, nullable=False)
    action = Column(String, nullable=False)
    new_verdict = Column(String, nullable=True)
    comment = Column(Text, default="")
    reviewer = Column(String, nullable=False)
    timestamp = Column(String, nullable=False)

    verdict = relationship("VerdictRow", back_populates="reviews")
