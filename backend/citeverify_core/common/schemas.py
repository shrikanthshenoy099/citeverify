"""
CiteVerify – shared Pydantic v2 data contracts (M4 owns).

Field names are FIXED across all modules. Do not rename without a team announcement.
"""

from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Reference
# ---------------------------------------------------------------------------

class Reference(BaseModel):
    reference_id: str
    raw_text: str
    title: Optional[str] = None
    authors: list[str] = Field(default_factory=list)
    year: Optional[int] = None
    doi: Optional[str] = None
    venue: Optional[str] = None
    parse_confidence: float = Field(ge=0.0, le=1.0, default=0.0)


# ---------------------------------------------------------------------------
# Claim
# ---------------------------------------------------------------------------

ClaimType = Literal["numeric", "factual", "conclusion", "methodological"]


class Claim(BaseModel):
    claim_id: str
    doc_id: str
    text: str
    page: Optional[int] = None
    section: Optional[str] = None
    char_start: int
    char_end: int
    citation_markers: list[str] = Field(default_factory=list)
    reference_ids: list[str] = Field(default_factory=list)
    claim_type: ClaimType = "factual"
    numbers_mentioned: list[str] = Field(default_factory=list)
    context_before: str = ""
    context_after: str = ""
    flags: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# ParsedDocument
# ---------------------------------------------------------------------------

class ParsedDocument(BaseModel):
    doc_id: str
    source_type: Literal["pdf", "docx", "text"]
    num_pages: Optional[int] = None
    references: list[Reference] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Source
# ---------------------------------------------------------------------------

TextLevel = Literal["full_text", "abstract_only", "metadata_only", "none"]


class Source(BaseModel):
    reference_id: str
    matched: bool
    match_score: float = Field(ge=0.0, le=1.0, default=0.0)
    title: str = ""
    authors: list[str] = Field(default_factory=list)
    year: Optional[int] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    pdf_path: Optional[str] = None
    text_level: TextLevel = "none"
    full_text_available: bool = False
    source_database: str = ""
    flags: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Passage
# ---------------------------------------------------------------------------

class Passage(BaseModel):
    passage_id: str
    reference_id: str
    text: str
    page: Optional[int] = None
    section: Optional[str] = None
    score: float = Field(ge=0.0, le=1.0, default=0.0)


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

class BBox(BaseModel):
    """PyMuPDF coordinate space: points, origin TOP-LEFT."""
    x0: float
    y0: float
    x1: float
    y1: float


class Evidence(BaseModel):
    quote: str
    passage_id: str
    page: Optional[int] = None
    section: Optional[str] = None
    bboxes: list[BBox] = Field(default_factory=list)
    page_width: Optional[float] = None
    page_height: Optional[float] = None


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

VerdictLabel = Literal[
    "supported",
    "partly_supported",
    "unsupported",
    "contradictory",
    "possibly_outdated",
    "needs_review",
]


class ConfidenceBreakdown(BaseModel):
    retrieval: float = Field(ge=0.0, le=1.0)
    llm_certainty: float = Field(ge=0.0, le=1.0)
    text_match: float = Field(ge=0.0, le=1.0)
    full_text: float = Field(ge=0.0, le=1.0)
    numeric_match: float = Field(ge=0.0, le=1.0)


class SourceTrace(BaseModel):
    doi: Optional[str] = None
    url: Optional[str] = None
    page: Optional[int] = None
    section: Optional[str] = None


class Verdict(BaseModel):
    claim_id: str
    reference_id: str
    verdict: VerdictLabel
    explanation: str
    evidence: Optional[Evidence] = None
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_breakdown: ConfidenceBreakdown
    source_trace: SourceTrace
    flags: list[str] = Field(default_factory=list)
    needs_human_review: bool = False


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------

ReviewAction = Literal["accept", "reject", "comment", "override"]


class Review(BaseModel):
    review_id: str
    claim_id: str
    reference_id: str
    action: ReviewAction
    new_verdict: Optional[VerdictLabel] = None
    comment: str = ""
    reviewer: str
    timestamp: str  # ISO-8601
