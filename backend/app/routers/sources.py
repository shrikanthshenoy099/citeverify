"""
backend/app/routers/sources.py

GET  /api/sources/{reference_id}/pdf   – stream stored source PDF
POST /api/references/{reference_id}/source – upload manual PDF, re-verify
"""

from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import SOURCES_DIR
from app.database import get_db
from app.models import ClaimRecord, DocumentRecord, ReferenceRecord, VerdictRecord
from app.services.orchestrator import _ingest_pdf, _upsert_verdict

logger = logging.getLogger(__name__)

router_sources = APIRouter(prefix="/api/sources", tags=["sources"])
router_references = APIRouter(prefix="/api/references", tags=["references"])


# ---------------------------------------------------------------------------
# GET /api/sources/{reference_id}/pdf
# ---------------------------------------------------------------------------


@router_sources.get("/{reference_id}/pdf")
def get_source_pdf(reference_id: str, db: Annotated[Session, Depends(get_db)]):
    """Stream the stored PDF for a retrieved source (if available)."""
    ref_rec = db.get(ReferenceRecord, reference_id)
    if ref_rec is None:
        raise HTTPException(404, f"Reference {reference_id!r} not found.")
    if not ref_rec.source_pdf_path:
        raise HTTPException(404, "No PDF stored for this reference.")
    p = Path(ref_rec.source_pdf_path)
    if not p.exists():
        raise HTTPException(404, "PDF file missing from storage.")
    return FileResponse(str(p), media_type="application/pdf",
                        filename=f"{reference_id}.pdf")


# ---------------------------------------------------------------------------
# POST /api/references/{reference_id}/source
# ---------------------------------------------------------------------------


def _reverify_background(reference_id: str, pdf_path: str, db_session_factory) -> None:
    """
    Background task: ingest the PDF, re-verify all claims citing it, persist.
    """
    from citeverify_core.common.schemas import Claim, Reference
    from citeverify_core.verification import verify

    db = db_session_factory()
    try:
        # 1. Ingest PDF → new Source
        source = _ingest_pdf(reference_id, pdf_path)

        # 2. Update the ReferenceRecord with new source info
        ref_rec = db.get(ReferenceRecord, reference_id)
        if ref_rec is None:
            logger.warning("reverify: ReferenceRecord %s not found.", reference_id)
            return

        ref_rec.source_pdf_path = pdf_path
        ref_rec.text_level = source.text_level
        ref_rec.source_flags = source.flags
        ref_rec.matched = source.matched
        ref_rec.source_json = source.model_dump()
        db.commit()

        # 3. Build Reference pydantic object from DB record
        reference = Reference(
            reference_id=ref_rec.reference_id,
            raw_text=ref_rec.raw_text,
            title=ref_rec.title,
            authors=ref_rec.authors or [],
            year=ref_rec.year,
            doi=ref_rec.doi,
            venue=ref_rec.venue,
            parse_confidence=ref_rec.parse_confidence,
        )

        # 4. Find all claims that cite this reference
        all_claim_records = db.execute(select(ClaimRecord)).scalars().all()
        claims_to_reverify = [
            c for c in all_claim_records
            if reference_id in (c.reference_ids or [])
        ]

        # 5. Re-verify each claim
        for claim_rec in claims_to_reverify:
            claim = Claim(
                claim_id=claim_rec.claim_id,
                doc_id=claim_rec.doc_id,
                text=claim_rec.text,
                page=claim_rec.page,
                section=claim_rec.section,
                char_start=claim_rec.char_start,
                char_end=claim_rec.char_end,
                citation_markers=claim_rec.citation_markers or [],
                reference_ids=claim_rec.reference_ids or [],
                claim_type=claim_rec.claim_type,
                numbers_mentioned=claim_rec.numbers_mentioned or [],
                context_before=claim_rec.context_before or "",
                context_after=claim_rec.context_after or "",
                flags=claim_rec.flags or [],
            )
            try:
                verdict = verify(claim, reference, source)
                _upsert_verdict(db, verdict)
                db.commit()
                logger.info(
                    "reverify: claim=%s ref=%s new_verdict=%s",
                    claim.claim_id, reference_id, verdict.verdict,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "reverify verify() failed claim=%s ref=%s: %s",
                    claim_rec.claim_id, reference_id, exc,
                )
    finally:
        db.close()


@router_references.post("/{reference_id}/source", status_code=202)
async def upload_source_pdf(
    reference_id: str,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
    file: UploadFile = File(...),
):
    """
    Upload a manual PDF for a reference.
    Triggers background re-verification of all claims that cite this reference.
    """
    ref_rec = db.get(ReferenceRecord, reference_id)
    if ref_rec is None:
        raise HTTPException(404, f"Reference {reference_id!r} not found.")

    suffix = Path(file.filename or "source.pdf").suffix.lower()
    if suffix != ".pdf":
        raise HTTPException(400, "Only PDF files are accepted here.")

    dest = SOURCES_DIR / f"{reference_id}.pdf"
    with dest.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)

    from app.database import SessionLocal

    background_tasks.add_task(
        _reverify_background,
        reference_id=reference_id,
        pdf_path=str(dest),
        db_session_factory=SessionLocal,
    )

    logger.info("Manual source PDF for %s queued for ingestion + reverify.", reference_id)
    return {"reference_id": reference_id, "status": "reverifying"}
