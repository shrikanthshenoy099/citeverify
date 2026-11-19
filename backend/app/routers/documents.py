"""
backend/app/routers/documents.py

POST   /api/documents                  – upload file or paste text
GET    /api/documents/{doc_id}/status  – poll pipeline status
GET    /api/documents/{doc_id}/results – full results (claims + verdicts)
GET    /api/documents/{doc_id}/export  – download CSV or PDF report
"""

from __future__ import annotations

import csv
import io
import logging
import mimetypes
import shutil
import uuid
from pathlib import Path
from typing import Annotated, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import UPLOAD_DIR
from app.database import get_db
from app.models import ClaimRecord, DocumentRecord, ReferenceRecord, VerdictRecord
from app.services.orchestrator import run_pipeline

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/documents", tags=["documents"])


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class DocumentStatusResponse(BaseModel):
    doc_id: str
    status: str
    source_type: str
    num_pages: Optional[int]
    warnings: list[str]
    created_at: str
    updated_at: str
    error_message: Optional[str] = None


class VerdictOut(BaseModel):
    reference_id: str
    verdict: str
    explanation: str
    confidence: float
    needs_human_review: bool
    flags: list[str]
    evidence: Optional[dict] = None
    confidence_breakdown: Optional[dict] = None
    source_trace: Optional[dict] = None


class ClaimOut(BaseModel):
    claim_id: str
    text: str
    page: Optional[int]
    section: Optional[str]
    claim_type: str
    numbers_mentioned: list[str]
    flags: list[str]
    verdicts: list[VerdictOut]


class DocumentResultsResponse(BaseModel):
    doc_id: str
    status: str
    source_type: str
    num_pages: Optional[int]
    warnings: list[str]
    claims: list[ClaimOut]


# ---------------------------------------------------------------------------
# POST /api/documents
# ---------------------------------------------------------------------------


@router.post("", status_code=202)
async def upload_document(
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
    file: Optional[UploadFile] = File(None),
    text: Optional[str] = Form(None),
):
    """
    Accept either a multipart file upload (PDF/DOCX) or a JSON/form body
    with a plain-text field.  Returns doc_id immediately; processing happens
    in the background.
    """
    if file is None and not text:
        raise HTTPException(400, "Provide either a file upload or a 'text' field.")

    doc_id = str(uuid.uuid4())
    file_path: Optional[str] = None
    source_type = "text"

    if file is not None:
        suffix = Path(file.filename or "upload").suffix.lower()
        if suffix not in (".pdf", ".docx"):
            raise HTTPException(400, f"Unsupported file type {suffix!r}. Use PDF or DOCX.")
        dest = UPLOAD_DIR / f"{doc_id}{suffix}"
        with dest.open("wb") as fh:
            shutil.copyfileobj(file.file, fh)
        file_path = str(dest)
        source_type = "pdf" if suffix == ".pdf" else "docx"

    doc_rec = DocumentRecord(
        doc_id=doc_id,
        source_type=source_type,
        original_filename=file.filename if file else None,
        file_path=file_path,
        status="pending",
        warnings=[],
    )
    db.add(doc_rec)
    db.commit()

    # Pass the SessionLocal factory (not the current session) to the background task
    from app.database import SessionLocal

    background_tasks.add_task(
        run_pipeline,
        doc_id=doc_id,
        file_path=file_path,
        raw_text=text,
        db_session_factory=SessionLocal,
    )

    logger.info("Document %s queued for processing (source_type=%s).", doc_id, source_type)
    return {"doc_id": doc_id, "status": "pending"}


# ---------------------------------------------------------------------------
# GET /api/documents/{doc_id}/status
# ---------------------------------------------------------------------------


@router.get("/{doc_id}/status", response_model=DocumentStatusResponse)
def get_status(doc_id: str, db: Annotated[Session, Depends(get_db)]):
    rec = _get_doc_or_404(db, doc_id)
    return DocumentStatusResponse(
        doc_id=rec.doc_id,
        status=rec.status,
        source_type=rec.source_type,
        num_pages=rec.num_pages,
        warnings=rec.warnings or [],
        created_at=rec.created_at.isoformat(),
        updated_at=rec.updated_at.isoformat(),
        error_message=rec.error_message,
    )


# ---------------------------------------------------------------------------
# GET /api/documents/{doc_id}/results
# ---------------------------------------------------------------------------


@router.get("/{doc_id}/results", response_model=DocumentResultsResponse)
def get_results(doc_id: str, db: Annotated[Session, Depends(get_db)]):
    rec = _get_doc_or_404(db, doc_id)

    claims_q = db.execute(
        select(ClaimRecord).where(ClaimRecord.doc_id == doc_id)
    ).scalars().all()

    claims_out: list[ClaimOut] = []
    for claim in claims_q:
        verdicts_q = db.execute(
            select(VerdictRecord).where(VerdictRecord.claim_id == claim.claim_id)
        ).scalars().all()

        verdicts_out = [
            VerdictOut(
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
        ]

        claims_out.append(
            ClaimOut(
                claim_id=claim.claim_id,
                text=claim.text,
                page=claim.page,
                section=claim.section,
                claim_type=claim.claim_type,
                numbers_mentioned=claim.numbers_mentioned or [],
                flags=claim.flags or [],
                verdicts=verdicts_out,
            )
        )

    return DocumentResultsResponse(
        doc_id=rec.doc_id,
        status=rec.status,
        source_type=rec.source_type,
        num_pages=rec.num_pages,
        warnings=rec.warnings or [],
        claims=claims_out,
    )


# ---------------------------------------------------------------------------
# GET /api/documents/{doc_id}/export
# ---------------------------------------------------------------------------


@router.get("/{doc_id}/export")
def export_document(
    doc_id: str,
    format: str = Query("csv", pattern="^(csv|pdf)$"),
    db: Annotated[Session, Depends(get_db)] = None,
):
    rec = _get_doc_or_404(db, doc_id)

    claims_q = db.execute(
        select(ClaimRecord).where(ClaimRecord.doc_id == doc_id)
    ).scalars().all()

    rows: list[dict] = []
    for claim in claims_q:
        verdicts_q = db.execute(
            select(VerdictRecord).where(VerdictRecord.claim_id == claim.claim_id)
        ).scalars().all()
        for v in verdicts_q:
            ref_rec = db.get(ReferenceRecord, v.reference_id)
            rows.append(
                {
                    "claim_id": claim.claim_id,
                    "claim_text": claim.text,
                    "page": claim.page,
                    "section": claim.section,
                    "claim_type": claim.claim_type,
                    "reference_id": v.reference_id,
                    "reference_title": ref_rec.source_title if ref_rec else "",
                    "verdict": v.verdict,
                    "confidence": f"{v.confidence:.2f}",
                    "needs_human_review": v.needs_human_review,
                    "flags": "|".join(v.flags or []),
                    "explanation": v.explanation,
                }
            )

    if format == "csv":
        return _export_csv(doc_id, rows)
    else:
        return _export_pdf(doc_id, rows)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_doc_or_404(db: Session, doc_id: str) -> DocumentRecord:
    rec = db.get(DocumentRecord, doc_id)
    if rec is None:
        raise HTTPException(404, f"Document {doc_id!r} not found.")
    return rec


def _export_csv(doc_id: str, rows: list[dict]) -> StreamingResponse:
    if not rows:
        fieldnames = [
            "claim_id", "claim_text", "page", "section", "claim_type",
            "reference_id", "reference_title", "verdict", "confidence",
            "needs_human_review", "flags", "explanation",
        ]
    else:
        fieldnames = list(rows[0].keys())

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    buf.seek(0)

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="citeverify_{doc_id}.csv"'},
    )


def _export_pdf(doc_id: str, rows: list[dict]) -> Response:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError:
        raise HTTPException(501, "PDF export requires 'reportlab'. Install requirements-m4.txt.")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=36, rightMargin=36)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph(f"CiteVerify Report — {doc_id}", styles["Title"]))
    story.append(Spacer(1, 12))

    if not rows:
        story.append(Paragraph("No claims or verdicts found.", styles["Normal"]))
    else:
        col_headers = ["Claim (truncated)", "Reference", "Verdict", "Conf.", "Review?"]
        table_data = [col_headers]
        for r in rows:
            table_data.append([
                Paragraph(r["claim_text"][:120] + ("…" if len(r["claim_text"]) > 120 else ""),
                          styles["Normal"]),
                Paragraph((r["reference_title"] or r["reference_id"])[:60], styles["Normal"]),
                r["verdict"],
                r["confidence"],
                "YES" if r["needs_human_review"] else "no",
            ])

        t = Table(table_data, colWidths=[200, 130, 70, 35, 45])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3b82d4")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f8fa")]),
        ]))
        story.append(t)

    story.append(Spacer(1, 20))
    story.append(Paragraph(
        "⚠️ CiteVerify assists human reviewers. This report is NOT a final academic judgment.",
        styles["Normal"],
    ))

    doc.build(story)
    buf.seek(0)
    return Response(
        content=buf.read(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="citeverify_{doc_id}.pdf"'},
    )
