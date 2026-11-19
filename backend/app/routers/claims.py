"""
backend/app/routers/claims.py

GET  /api/claims/{claim_id}           – claim detail with all verdicts
POST /api/claims/{claim_id}/review    – submit a human review
GET  /api/claims/{claim_id}/reviews   – list all reviews for a claim
"""

from __future__ import annotations

import datetime
import logging
import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ClaimRecord, ReviewRecord, VerdictRecord

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/claims", tags=["claims"])


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class VerdictDetail(BaseModel):
    reference_id: str
    verdict: str
    explanation: str
    confidence: float
    needs_human_review: bool
    flags: list[str]
    evidence: Optional[dict] = None
    confidence_breakdown: Optional[dict] = None
    source_trace: Optional[dict] = None


class ClaimDetailResponse(BaseModel):
    claim_id: str
    doc_id: str
    text: str
    page: Optional[int]
    section: Optional[str]
    char_start: int
    char_end: int
    claim_type: str
    citation_markers: list[str]
    reference_ids: list[str]
    numbers_mentioned: list[str]
    context_before: str
    context_after: str
    flags: list[str]
    verdicts: list[VerdictDetail]


class ReviewRequest(BaseModel):
    reference_id: str
    action: str           # accept | reject | comment | override
    new_verdict: Optional[str] = None
    comment: str = ""
    reviewer: str


class ReviewResponse(BaseModel):
    review_id: str
    claim_id: str
    reference_id: str
    action: str
    new_verdict: Optional[str]
    comment: str
    reviewer: str
    timestamp: str


# ---------------------------------------------------------------------------
# GET /api/claims/{claim_id}
# ---------------------------------------------------------------------------


@router.get("/{claim_id}", response_model=ClaimDetailResponse)
def get_claim(claim_id: str, db: Annotated[Session, Depends(get_db)]):
    claim = _get_claim_or_404(db, claim_id)

    verdicts_q = db.execute(
        select(VerdictRecord).where(VerdictRecord.claim_id == claim_id)
    ).scalars().all()

    return ClaimDetailResponse(
        claim_id=claim.claim_id,
        doc_id=claim.doc_id,
        text=claim.text,
        page=claim.page,
        section=claim.section,
        char_start=claim.char_start,
        char_end=claim.char_end,
        claim_type=claim.claim_type,
        citation_markers=claim.citation_markers or [],
        reference_ids=claim.reference_ids or [],
        numbers_mentioned=claim.numbers_mentioned or [],
        context_before=claim.context_before or "",
        context_after=claim.context_after or "",
        flags=claim.flags or [],
        verdicts=[
            VerdictDetail(
                reference_id=v.reference_id,
                verdict=v.verdict,
                explanation=v.explanation,
                confidence=v.confidence,
                needs_human_review=bool(v.needs_human_review),
                flags=v.flags or [],
                evidence=(v.verdict_json or {}).get("evidence"),
                confidence_breakdown=(v.verdict_json or {}).get("confidence_breakdown"),
                source_trace=(v.verdict_json or {}).get("source_trace"),
            )
            for v in verdicts_q
        ],
    )


# ---------------------------------------------------------------------------
# POST /api/claims/{claim_id}/review
# ---------------------------------------------------------------------------

_VALID_ACTIONS = {"accept", "reject", "comment", "override"}
_VALID_VERDICTS = {
    "supported", "partly_supported", "unsupported",
    "contradictory", "possibly_outdated", "needs_review",
}


@router.post("/{claim_id}/review", response_model=ReviewResponse, status_code=201)
def submit_review(
    claim_id: str,
    body: ReviewRequest,
    db: Annotated[Session, Depends(get_db)],
):
    _get_claim_or_404(db, claim_id)

    if body.action not in _VALID_ACTIONS:
        raise HTTPException(422, f"Invalid action {body.action!r}. Valid: {_VALID_ACTIONS}")
    if body.action == "override" and body.new_verdict not in _VALID_VERDICTS:
        raise HTTPException(422, f"new_verdict required for override action.")
    if not body.reviewer.strip():
        raise HTTPException(422, "reviewer must not be empty.")

    review_id = str(uuid.uuid4())
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()

    record = ReviewRecord(
        review_id=review_id,
        claim_id=claim_id,
        reference_id=body.reference_id,
        action=body.action,
        new_verdict=body.new_verdict,
        comment=body.comment,
        reviewer=body.reviewer.strip(),
        timestamp=ts,
    )
    db.add(record)
    db.commit()
    logger.info("Review %s submitted by %r for claim %s.", review_id, body.reviewer, claim_id)

    return ReviewResponse(
        review_id=review_id,
        claim_id=claim_id,
        reference_id=body.reference_id,
        action=body.action,
        new_verdict=body.new_verdict,
        comment=body.comment,
        reviewer=body.reviewer,
        timestamp=ts,
    )


# ---------------------------------------------------------------------------
# GET /api/claims/{claim_id}/reviews
# ---------------------------------------------------------------------------


@router.get("/{claim_id}/reviews", response_model=list[ReviewResponse])
def list_reviews(claim_id: str, db: Annotated[Session, Depends(get_db)]):
    _get_claim_or_404(db, claim_id)

    records = db.execute(
        select(ReviewRecord).where(ReviewRecord.claim_id == claim_id)
    ).scalars().all()

    return [
        ReviewResponse(
            review_id=r.review_id,
            claim_id=r.claim_id,
            reference_id=r.reference_id,
            action=r.action,
            new_verdict=r.new_verdict,
            comment=r.comment,
            reviewer=r.reviewer,
            timestamp=r.timestamp,
        )
        for r in records
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_claim_or_404(db: Session, claim_id: str) -> ClaimRecord:
    rec = db.get(ClaimRecord, claim_id)
    if rec is None:
        raise HTTPException(404, f"Claim {claim_id!r} not found.")
    return rec
