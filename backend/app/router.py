"""
app/router.py – all CiteVerify REST endpoints.

Endpoints:
  POST   /api/documents                              upload file or paste text
  GET    /api/documents/{doc_id}/status              poll status
  GET    /api/documents/{doc_id}/results             full report
  GET    /api/documents/{doc_id}/export              CSV or PDF download
  GET    /api/claims/{claim_id}                      single claim
  POST   /api/claims/{claim_id}/review               submit review
  GET    /api/claims/{claim_id}/reviews              list reviews
  GET    /api/sources/{reference_id}/pdf             serve source PDF
  POST   /api/references/{reference_id}/source       upload manual source PDF
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db, get_db_context
from app.export import export_csv, export_pdf
from app.models import (
    ClaimRecord,
    DocumentRecord,
    ReferenceRecord,
    ReviewRecord,
    VerdictRecord,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response schemas (API-layer only)
# ---------------------------------------------------------------------------

class DocumentStatusResponse(BaseModel):
    doc_id: str
    status: str
    source_type: str
    num_pages: Optional[int] = None
    warnings: list[str]
    num_claims: int
    num_references: int


class ClaimResponse(BaseModel):
    claim_id: str
    doc_id: str
    text: str
    page: Optional[int] = None
    section: Optional[str] = None
    claim_type: str
    citation_markers: list[str]
    reference_ids: list[str]
    numbers_mentioned: list[str]
    flags: list[str]
    verdicts: list[dict]


class ReviewRequest(BaseModel):
    action: str           # accept | reject | comment | override
    new_verdict: Optional[str] = None
    comment: str = ""
    reviewer: str


class ReviewResponse(BaseModel):
    review_id: str
    claim_id: str
    reference_id: str
    action: str
    new_verdict: Optional[str] = None
    comment: str
    reviewer: str
    timestamp: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_document_or_404(doc_id: str, db: Session) -> DocumentRecord:
    doc = db.query(DocumentRecord).filter(DocumentRecord.id == doc_id).first()
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Document {doc_id!r} not found.")
    return doc


def _get_claim_or_404(claim_id: str, db: Session) -> ClaimRecord:
    claim = db.query(ClaimRecord).filter(ClaimRecord.id == claim_id).first()
    if claim is None:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id!r} not found.")
    return claim


def _verdict_record_to_dict(v: VerdictRecord) -> dict:
    return {
        "reference_id": v.reference_id,
        "verdict": v.verdict,
        "confidence": v.confidence,
        "needs_human_review": v.needs_human_review,
        "explanation": v.explanation,
        "flags": v.flags or [],
        "evidence": v.evidence_json,
        "confidence_breakdown": v.confidence_breakdown_json,
        "source_trace": v.source_trace_json,
    }


# ---------------------------------------------------------------------------
# Background task: run pipeline and persist results
# ---------------------------------------------------------------------------

def _run_pipeline_bg(doc_id: str, file_path: Optional[str], raw_text: Optional[str]):
    """
    Synchronous background task – runs in FastAPI's thread pool via BackgroundTasks.
    """
    from app.orchestrator import run_pipeline

    # Update status → processing
    with get_db_context() as db:
        doc = db.query(DocumentRecord).filter(DocumentRecord.id == doc_id).first()
        if doc:
            doc.status = "processing"

    try:
        parsed, sources, verdicts = run_pipeline(file_path, raw_text, doc_id)
    except Exception as exc:
        logger.error("[M4] Pipeline error for doc=%s: %s", doc_id, exc)
        with get_db_context() as db:
            doc = db.query(DocumentRecord).filter(DocumentRecord.id == doc_id).first()
            if doc:
                doc.status = "error"
                doc.error_message = str(exc)
        return

    with get_db_context() as db:
        doc = db.query(DocumentRecord).filter(DocumentRecord.id == doc_id).first()
        if doc is None:
            return
        doc.status = "done"
        doc.source_type = parsed.source_type
        doc.num_pages = parsed.num_pages
        doc.warnings = parsed.warnings

        for ref in parsed.references:
            rec = ReferenceRecord(
                id=ref.reference_id,
                doc_id=doc_id,
                raw_text=ref.raw_text,
                title=ref.title,
                authors=ref.authors,
                year=ref.year,
                doi=ref.doi,
                venue=ref.venue,
                parse_confidence=ref.parse_confidence,
            )
            db.add(rec)

        for claim in parsed.claims:
            rec = ClaimRecord(
                id=claim.claim_id,
                doc_id=doc_id,
                text=claim.text,
                page=claim.page,
                section=claim.section,
                char_start=claim.char_start,
                char_end=claim.char_end,
                citation_markers=claim.citation_markers,
                reference_ids=claim.reference_ids,
                claim_type=claim.claim_type,
                numbers_mentioned=claim.numbers_mentioned,
                context_before=claim.context_before,
                context_after=claim.context_after,
                flags=claim.flags,
            )
            db.add(rec)

        for v in verdicts:
            rec = VerdictRecord(
                id=str(uuid.uuid4()),
                claim_id=v.claim_id,
                reference_id=v.reference_id,
                verdict=v.verdict,
                explanation=v.explanation,
                confidence=v.confidence,
                needs_human_review=v.needs_human_review,
                evidence_json=v.evidence.model_dump() if v.evidence else None,
                confidence_breakdown_json=v.confidence_breakdown.model_dump(),
                source_trace_json=v.source_trace.model_dump(),
                flags=v.flags,
            )
            db.add(rec)

    logger.info("[M4] Results persisted for doc=%s", doc_id)


# ---------------------------------------------------------------------------
# POST /api/documents
# ---------------------------------------------------------------------------

@router.post("/api/documents", status_code=202)
async def upload_document(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    file: Optional[UploadFile] = File(default=None),
    text: Optional[str] = Form(default=None),
):
    """
    Upload a PDF or DOCX, or paste plain text.
    Returns 202 immediately; poll GET /api/documents/{id}/status for results.
    """
    if file is None and not text:
        raise HTTPException(status_code=422, detail="Provide either 'file' or 'text'.")

    doc_id = str(uuid.uuid4())
    settings = get_settings()
    file_path: Optional[str] = None
    raw_text: Optional[str] = None
    source_type = "text"
    original_filename: Optional[str] = None

    if file is not None:
        suffix = Path(file.filename or "upload").suffix.lower()
        source_type = "pdf" if suffix == ".pdf" else "docx"
        original_filename = file.filename
        dest = settings.upload_dir / f"{doc_id}{suffix}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        content = await file.read()
        dest.write_bytes(content)
        file_path = str(dest)
    else:
        raw_text = text

    doc = DocumentRecord(
        id=doc_id,
        source_type=source_type,
        original_filename=original_filename,
        status="pending",
        warnings=[],
    )
    db.add(doc)
    db.commit()

    background_tasks.add_task(_run_pipeline_bg, doc_id, file_path, raw_text)
    return {"doc_id": doc_id, "status": "pending"}


# ---------------------------------------------------------------------------
# GET /api/documents/{doc_id}/status
# ---------------------------------------------------------------------------

@router.get("/api/documents/{doc_id}/status", response_model=DocumentStatusResponse)
def get_document_status(doc_id: str, db: Session = Depends(get_db)):
    """Poll the processing status of a document."""
    doc = _get_document_or_404(doc_id, db)
    num_claims = db.query(ClaimRecord).filter(ClaimRecord.doc_id == doc_id).count()
    num_refs = db.query(ReferenceRecord).filter(ReferenceRecord.doc_id == doc_id).count()

    return DocumentStatusResponse(
        doc_id=doc.id,
        status=doc.status,
        source_type=doc.source_type,
        num_pages=doc.num_pages,
        warnings=doc.warnings or [],
        num_claims=num_claims,
        num_references=num_refs,
    )


# ---------------------------------------------------------------------------
# GET /api/documents/{doc_id}/results
# ---------------------------------------------------------------------------

@router.get("/api/documents/{doc_id}/results")
def get_document_results(doc_id: str, db: Session = Depends(get_db)):
    """Return the full verification report for a document."""
    doc = _get_document_or_404(doc_id, db)

    if doc.status not in ("done", "error"):
        raise HTTPException(
            status_code=202,
            detail=f"Document is still {doc.status!r}. Poll /status first.",
        )

    claims = db.query(ClaimRecord).filter(ClaimRecord.doc_id == doc_id).all()
    refs = db.query(ReferenceRecord).filter(ReferenceRecord.doc_id == doc_id).all()
    claim_ids = [c.id for c in claims]
    verdicts = (
        db.query(VerdictRecord).filter(VerdictRecord.claim_id.in_(claim_ids)).all()
        if claim_ids else []
    )
    verdict_map: dict[tuple[str, str], VerdictRecord] = {
        (v.claim_id, v.reference_id): v for v in verdicts
    }

    claim_items = []
    for c in claims:
        claim_verdicts = [
            _verdict_record_to_dict(verdict_map[(c.id, rid)])
            for rid in (c.reference_ids or [])
            if (c.id, rid) in verdict_map
        ]
        claim_items.append({
            "claim_id": c.id,
            "text": c.text,
            "page": c.page,
            "section": c.section,
            "claim_type": c.claim_type,
            "citation_markers": c.citation_markers or [],
            "reference_ids": c.reference_ids or [],
            "numbers_mentioned": c.numbers_mentioned or [],
            "flags": c.flags or [],
            "verdicts": claim_verdicts,
        })

    return {
        "doc_id": doc_id,
        "status": doc.status,
        "source_type": doc.source_type,
        "num_pages": doc.num_pages,
        "warnings": doc.warnings or [],
        "references": [
            {
                "reference_id": r.id,
                "title": r.title,
                "authors": r.authors or [],
                "year": r.year,
                "doi": r.doi,
                "venue": r.venue,
                "parse_confidence": r.parse_confidence,
            }
            for r in refs
        ],
        "claims": claim_items,
    }


# ---------------------------------------------------------------------------
# GET /api/documents/{doc_id}/export
# ---------------------------------------------------------------------------

@router.get("/api/documents/{doc_id}/export")
def export_document(
    doc_id: str,
    format: str = "csv",
    db: Session = Depends(get_db),
):
    """Export the verification report as CSV or PDF."""
    if format not in ("csv", "pdf"):
        raise HTTPException(status_code=422, detail="format must be 'csv' or 'pdf'.")

    doc = _get_document_or_404(doc_id, db)
    if doc.status != "done":
        raise HTTPException(status_code=409, detail="Document processing not complete.")

    claims = list(db.query(ClaimRecord).filter(ClaimRecord.doc_id == doc_id).all())
    claim_ids = [c.id for c in claims]
    verdicts = (
        list(db.query(VerdictRecord).filter(VerdictRecord.claim_id.in_(claim_ids)).all())
        if claim_ids else []
    )

    if format == "csv":
        content = export_csv(claims, verdicts)
        return Response(
            content=content,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=citeverify_{doc_id}.csv"},
        )
    else:
        content = export_pdf(doc_id, claims, verdicts)
        if not content:
            raise HTTPException(
                status_code=500, detail="PDF generation failed (reportlab missing?)."
            )
        return Response(
            content=content,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=citeverify_{doc_id}.pdf"},
        )


# ---------------------------------------------------------------------------
# GET /api/claims/{claim_id}
# ---------------------------------------------------------------------------

@router.get("/api/claims/{claim_id}", response_model=ClaimResponse)
def get_claim(claim_id: str, db: Session = Depends(get_db)):
    """Return a single claim with all its verdicts."""
    claim = _get_claim_or_404(claim_id, db)
    verdicts = db.query(VerdictRecord).filter(VerdictRecord.claim_id == claim_id).all()

    return ClaimResponse(
        claim_id=claim.id,
        doc_id=claim.doc_id,
        text=claim.text,
        page=claim.page,
        section=claim.section,
        claim_type=claim.claim_type,
        citation_markers=claim.citation_markers or [],
        reference_ids=claim.reference_ids or [],
        numbers_mentioned=claim.numbers_mentioned or [],
        flags=claim.flags or [],
        verdicts=[_verdict_record_to_dict(v) for v in verdicts],
    )


# ---------------------------------------------------------------------------
# POST /api/claims/{claim_id}/review
# ---------------------------------------------------------------------------

@router.post("/api/claims/{claim_id}/review", status_code=201, response_model=ReviewResponse)
def submit_review(
    claim_id: str,
    body: ReviewRequest,
    db: Session = Depends(get_db),
):
    """Submit a human review action for a claim."""
    claim = _get_claim_or_404(claim_id, db)

    ref_ids: list[str] = claim.reference_ids or []
    reference_id = ref_ids[0] if ref_ids else "unknown"

    valid_actions = {"accept", "reject", "comment", "override"}
    if body.action not in valid_actions:
        raise HTTPException(
            status_code=422,
            detail=f"action must be one of: {', '.join(sorted(valid_actions))}",
        )

    review = ReviewRecord(
        id=str(uuid.uuid4()),
        claim_id=claim_id,
        reference_id=reference_id,
        action=body.action,
        new_verdict=body.new_verdict,
        comment=body.comment,
        reviewer=body.reviewer,
        timestamp=_now_iso(),
    )
    db.add(review)
    db.commit()

    return ReviewResponse(
        review_id=review.id,
        claim_id=review.claim_id,
        reference_id=review.reference_id,
        action=review.action,
        new_verdict=review.new_verdict,
        comment=review.comment,
        reviewer=review.reviewer,
        timestamp=review.timestamp,
    )


# ---------------------------------------------------------------------------
# GET /api/claims/{claim_id}/reviews
# ---------------------------------------------------------------------------

@router.get("/api/claims/{claim_id}/reviews", response_model=list[ReviewResponse])
def list_reviews(claim_id: str, db: Session = Depends(get_db)):
    """List all human reviews for a claim."""
    _get_claim_or_404(claim_id, db)
    reviews = db.query(ReviewRecord).filter(ReviewRecord.claim_id == claim_id).all()
    return [
        ReviewResponse(
            review_id=r.id,
            claim_id=r.claim_id,
            reference_id=r.reference_id,
            action=r.action,
            new_verdict=r.new_verdict,
            comment=r.comment,
            reviewer=r.reviewer,
            timestamp=r.timestamp,
        )
        for r in reviews
    ]


# ---------------------------------------------------------------------------
# GET /api/sources/{reference_id}/pdf
# ---------------------------------------------------------------------------

@router.get("/api/sources/{reference_id}/pdf")
def get_source_pdf(reference_id: str, db: Session = Depends(get_db)):
    """Serve the source PDF for a reference (if available)."""
    ref = db.query(ReferenceRecord).filter(ReferenceRecord.id == reference_id).first()
    if ref is None:
        raise HTTPException(status_code=404, detail=f"Reference {reference_id!r} not found.")

    settings = get_settings()
    pdf_path = settings.sources_dir / f"{reference_id}.pdf"
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="Source PDF not available.")

    return FileResponse(str(pdf_path), media_type="application/pdf")


# ---------------------------------------------------------------------------
# POST /api/references/{reference_id}/source
# ---------------------------------------------------------------------------

@router.post("/api/references/{reference_id}/source", status_code=202)
async def upload_manual_source(
    reference_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    file: UploadFile = File(...),
):
    """
    Upload a manual source PDF for a reference, then re-verify all claims
    that cite it via M2.ingest_pdf + M3.verify.
    """
    ref = db.query(ReferenceRecord).filter(ReferenceRecord.id == reference_id).first()
    if ref is None:
        raise HTTPException(status_code=404, detail=f"Reference {reference_id!r} not found.")

    settings = get_settings()
    dest = settings.sources_dir / f"{reference_id}.pdf"
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    dest.write_bytes(content)
    logger.info("[M4] Manual source PDF saved: %s", dest)

    background_tasks.add_task(_reverify_bg, reference_id, str(dest), ref.doc_id)
    return {"reference_id": reference_id, "status": "reverification_queued"}


def _reverify_bg(reference_id: str, pdf_path: str, doc_id: str):
    """Synchronous background task: ingest PDF + re-verify claims."""
    from app.orchestrator import run_reverify_for_reference

    try:
        from citeverify_core.retrieval import ingest_pdf  # type: ignore
    except ImportError:
        logger.error("[M4] M2 ingest_pdf not available; cannot reverify.")
        return

    with get_db_context() as db:
        ref_rec = db.query(ReferenceRecord).filter(ReferenceRecord.id == reference_id).first()
        if ref_rec is None:
            return

        from citeverify_core.common.schemas import Reference, Claim
        reference = Reference(
            reference_id=ref_rec.id,
            raw_text=ref_rec.raw_text,
            title=ref_rec.title,
            authors=ref_rec.authors or [],
            year=ref_rec.year,
            doi=ref_rec.doi,
            venue=ref_rec.venue,
            parse_confidence=ref_rec.parse_confidence,
        )

        try:
            source = ingest_pdf(reference_id, pdf_path)
        except Exception as exc:
            logger.error("[M4] ingest_pdf failed for ref %s: %s", reference_id, exc)
            return

        all_claim_recs = (
            db.query(ClaimRecord).filter(ClaimRecord.doc_id == doc_id).all()
        )
        affected_claims = [
            Claim(
                claim_id=c.id,
                doc_id=c.doc_id,
                text=c.text,
                page=c.page,
                section=c.section,
                char_start=c.char_start,
                char_end=c.char_end,
                citation_markers=c.citation_markers or [],
                reference_ids=c.reference_ids or [],
                claim_type=c.claim_type,
                numbers_mentioned=c.numbers_mentioned or [],
                context_before=c.context_before or "",
                context_after=c.context_after or "",
                flags=c.flags or [],
            )
            for c in all_claim_recs
            if reference_id in (c.reference_ids or [])
        ]

        new_verdicts = run_reverify_for_reference(
            reference_id, affected_claims, reference, source
        )

        for v in new_verdicts:
            old = (
                db.query(VerdictRecord)
                .filter(
                    VerdictRecord.claim_id == v.claim_id,
                    VerdictRecord.reference_id == v.reference_id,
                )
                .first()
            )
            if old:
                db.delete(old)
            db.add(
                VerdictRecord(
                    id=str(uuid.uuid4()),
                    claim_id=v.claim_id,
                    reference_id=v.reference_id,
                    verdict=v.verdict,
                    explanation=v.explanation,
                    confidence=v.confidence,
                    needs_human_review=v.needs_human_review,
                    evidence_json=v.evidence.model_dump() if v.evidence else None,
                    confidence_breakdown_json=v.confidence_breakdown.model_dump(),
                    source_trace_json=v.source_trace.model_dump(),
                    flags=v.flags,
                )
            )

    logger.info(
        "[M4] Reverify done for ref=%s: %d verdicts updated.", reference_id, len(new_verdicts)
    )
