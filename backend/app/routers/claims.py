"""
app/routers/claims.py – Claims and reviews endpoints.

GET  /api/claims/{claim_id}
POST /api/claims/{claim_id}/review
GET  /api/claims/{claim_id}/reviews
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models import ClaimRow, ReviewRow, VerdictRow
from app.db.session import get_db
from citeverify_core.common.schemas import ReviewAction, VerdictLabel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/claims", tags=["claims"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class ReviewRequest(BaseModel):
    reference_id: Optional[str] = None
    action: ReviewAction
    new_verdict: Optional[VerdictLabel] = None
    comment: str = ""
    reviewer: str


# ---------------------------------------------------------------------------
# GET /api/claims/{claim_id}
# ---------------------------------------------------------------------------

@router.get("/{claim_id}")
def get_claim(claim_id: str, db: Session = Depends(get_db)):
    row = db.get(ClaimRow, claim_id)
    if row is None:
        raise HTTPException(404, f"Claim {claim_id!r} not found")
    claim = json.loads(row.payload)
    verdicts = (
        db.query(VerdictRow)
        .filter(VerdictRow.claim_id == claim_id)
        .all()
    )
    claim["verdicts"] = [json.loads(v.payload) for v in verdicts]
    return claim


# ---------------------------------------------------------------------------
# POST /api/claims/{claim_id}/review
# ---------------------------------------------------------------------------

@router.post("/{claim_id}/review", status_code=201)
def post_review(
    claim_id: str,
    body: ReviewRequest,
    db: Session = Depends(get_db),
):
    # Resolve reference_id: use the supplied value or fall back to the claim's
    # first verdict (convenient for single-citation claims / UI usage).
    reference_id = body.reference_id
    if reference_id is None:
        first_verdict = (
            db.query(VerdictRow)
            .filter(VerdictRow.claim_id == claim_id)
            .first()
        )
        if first_verdict is None:
            raise HTTPException(404, f"Claim {claim_id!r} not found or has no verdicts")
        reference_id = first_verdict.reference_id

    # Validate that the (claim, reference) verdict exists
    verdict = (
        db.query(VerdictRow)
        .filter(
            VerdictRow.claim_id == claim_id,
            VerdictRow.reference_id == reference_id,
        )
        .first()
    )
    if verdict is None:
        raise HTTPException(
            404,
            f"No verdict found for claim={claim_id!r} reference={reference_id!r}",
        )

    review = ReviewRow(
        review_id=str(uuid.uuid4()),
        claim_id=claim_id,
        reference_id=reference_id,
        action=body.action,
        new_verdict=body.new_verdict,
        comment=body.comment,
        reviewer=body.reviewer,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    db.add(review)
    db.commit()
    logger.info(
        "Review created: claim=%s ref=%s action=%s reviewer=%s",
        claim_id, reference_id, body.action, body.reviewer,
    )
    return {
        "review_id": review.review_id,
        "claim_id": claim_id,
        "reference_id": reference_id,
        "action": body.action,
        "reviewer": body.reviewer,
        "timestamp": review.timestamp,
    }


# ---------------------------------------------------------------------------
# GET /api/claims/{claim_id}/reviews
# ---------------------------------------------------------------------------

@router.get("/{claim_id}/reviews")
def get_reviews(claim_id: str, db: Session = Depends(get_db)):
    rows = (
        db.query(ReviewRow)
        .filter(ReviewRow.claim_id == claim_id)
        .order_by(ReviewRow.timestamp.asc())
        .all()
    )
    return [
        {
            "review_id": r.review_id,
            "claim_id": r.claim_id,
            "reference_id": r.reference_id,
            "action": r.action,
            "new_verdict": r.new_verdict,
            "comment": r.comment,
            "reviewer": r.reviewer,
            "timestamp": r.timestamp,
        }
        for r in rows
    ]
