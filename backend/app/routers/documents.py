"""
app/routers/documents.py – Document upload and status endpoints.

POST /api/documents    – upload PDF/DOCX file OR submit raw text
GET  /api/documents/{id}/status
GET  /api/documents/{id}/results
GET  /api/documents/{id}/export?format=csv|pdf
"""

from __future__ import annotations

import csv
import io
import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import ClaimRow, DocumentRow, ReferenceRow, ReviewRow, SourceRow, VerdictRow
from app.db.session import SessionLocal, get_db
from app.orchestrator import run_pipeline

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/documents", tags=["documents"])

ALLOWED_MIME = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/octet-stream",  # some browsers send this for PDFs
}


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class TextSubmission(BaseModel):
    text: str


class DocumentStatusResponse(BaseModel):
    doc_id: str
    status: str
    error_message: Optional[str] = None


# ---------------------------------------------------------------------------
# POST /api/documents
# ---------------------------------------------------------------------------

@router.post("", status_code=202)
async def upload_document(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    file: Optional[UploadFile] = File(default=None),
    text: Optional[str] = Form(default=None),
):
    """
    Accept either a multipart file upload (PDF or DOCX) OR a form field
    ``text`` containing pasted content.  Returns ``{doc_id}`` immediately;
    pipeline runs in the background.
    """
    if file is None and not text:
        raise HTTPException(422, "Provide either a file upload or a 'text' field")

    doc_id = str(uuid.uuid4())
    file_path: Optional[str] = None
    source_type: str = "text"

    if file is not None:
        fname = file.filename or "upload"
        ext = Path(fname).suffix.lower()
        if ext not in (".pdf", ".docx"):
            raise HTTPException(400, "Only PDF and DOCX files are supported")

        content = await file.read()
        if len(content) > settings.max_upload_bytes:
            raise HTTPException(413, f"File exceeds {settings.max_upload_bytes // (1024*1024)} MB limit")

        dest = settings.uploads_dir / doc_id
        dest.mkdir(parents=True, exist_ok=True)
        dest_file = dest / fname
        dest_file.write_bytes(content)
        file_path = str(dest_file)
        source_type = "pdf" if ext == ".pdf" else "docx"

    # Persist document row
    doc_row = DocumentRow(
        doc_id=doc_id,
        filename=file.filename if file else None,
        source_type=source_type,
        status="pending",
    )
    db.add(doc_row)
    db.commit()

    # Schedule pipeline
    background_tasks.add_task(
        _run_pipeline_sync,
        doc_id=doc_id,
        file_path=file_path,
        raw_text=text,
    )
    logger.info("Document %s queued for pipeline (source_type=%s)", doc_id, source_type)
    return {"doc_id": doc_id, "status": "pending"}


def _run_pipeline_sync(doc_id: str, file_path: Optional[str], raw_text: Optional[str]) -> None:
    """Runs in BackgroundTasks (synchronous thread)."""
    db = SessionLocal()
    try:
        run_pipeline(doc_id=doc_id, db=db, file_path=file_path, raw_text=raw_text)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GET /api/documents/{id}/status
# ---------------------------------------------------------------------------

@router.get("/{doc_id}/status", response_model=DocumentStatusResponse)
def get_status(doc_id: str, db: Session = Depends(get_db)):
    row = db.get(DocumentRow, doc_id)
    if row is None:
        raise HTTPException(404, f"Document {doc_id!r} not found")
    return DocumentStatusResponse(
        doc_id=row.doc_id,
        status=row.status,
        error_message=row.error_message,
    )


# ---------------------------------------------------------------------------
# GET /api/documents/{id}/results
# ---------------------------------------------------------------------------

@router.get("/{doc_id}/results")
def get_results(doc_id: str, db: Session = Depends(get_db)):
    """Return claims with their verdicts grouped for the UI."""
    row = db.get(DocumentRow, doc_id)
    if row is None:
        raise HTTPException(404, f"Document {doc_id!r} not found")

    claims = db.query(ClaimRow).filter(ClaimRow.doc_id == doc_id).all()
    refs = db.query(ReferenceRow).filter(ReferenceRow.doc_id == doc_id).all()

    ref_map = {r.reference_id: json.loads(r.payload) for r in refs}

    result_claims = []
    for cr in claims:
        claim_data = json.loads(cr.payload)
        verdicts = (
            db.query(VerdictRow)
            .filter(VerdictRow.claim_id == cr.claim_id)
            .all()
        )
        claim_data["verdicts"] = [json.loads(v.payload) for v in verdicts]
        result_claims.append(claim_data)

    return {
        "doc_id": doc_id,
        "status": row.status,
        "claims": result_claims,
        "references": list(ref_map.values()),
    }


# ---------------------------------------------------------------------------
# GET /api/documents/{id}/export
# ---------------------------------------------------------------------------

@router.get("/{doc_id}/export")
def export_results(
    doc_id: str,
    format: str = Query("csv", pattern="^(csv|pdf)$"),
    db: Session = Depends(get_db),
):
    row = db.get(DocumentRow, doc_id)
    if row is None:
        raise HTTPException(404, f"Document {doc_id!r} not found")

    claims = db.query(ClaimRow).filter(ClaimRow.doc_id == doc_id).all()

    if format == "csv":
        return _export_csv(doc_id, claims, db)
    return _export_pdf(doc_id, row, claims, db)


def _export_csv(doc_id: str, claims, db: Session) -> StreamingResponse:
    output = io.StringIO()
    writer = csv.writer(output)
    # Disclaimer row
    writer.writerow(["# Automated analysis to assist human review. Not a final academic judgment."])
    writer.writerow([
        "claim_id", "claim_text", "claim_type", "page", "section",
        "citation_markers", "reference_id", "verdict", "confidence",
        "needs_human_review", "flags", "explanation",
        "evidence_quote", "evidence_page", "evidence_section",
        "doi", "url",
        "latest_review_action", "latest_reviewer", "latest_review_comment",
    ])
    for cr in claims:
        claim = json.loads(cr.payload)
        citation_markers = ";".join(claim.get("citation_markers", []))
        verdicts = db.query(VerdictRow).filter(VerdictRow.claim_id == cr.claim_id).all()
        if not verdicts:
            writer.writerow([
                claim["claim_id"], claim["text"], claim["claim_type"],
                claim.get("page", ""), claim.get("section", ""),
                citation_markers,
                "", "", "", "", "", "", "", "", "", "", "", "", "",
            ])
            continue
        for vr in verdicts:
            v = json.loads(vr.payload)
            ev = v.get("evidence") or {}
            # Latest review for this (claim, reference) pair
            latest = (
                db.query(ReviewRow)
                .filter(
                    ReviewRow.claim_id == cr.claim_id,
                    ReviewRow.reference_id == v["reference_id"],
                )
                .order_by(ReviewRow.timestamp.desc())
                .first()
            )
            writer.writerow([
                claim["claim_id"], claim["text"], claim["claim_type"],
                claim.get("page", ""), claim.get("section", ""),
                citation_markers,
                v["reference_id"], v["verdict"], v["confidence"],
                v["needs_human_review"],
                ";".join(v.get("flags", [])),
                v["explanation"],
                ev.get("quote", ""),
                ev.get("page", ""),
                ev.get("section", ""),
                v.get("source_trace", {}).get("doi", ""),
                v.get("source_trace", {}).get("url", ""),
                latest.action if latest else "",
                latest.reviewer if latest else "",
                latest.comment if latest else "",
            ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=citeverify-{doc_id}.csv"},
    )


def _export_pdf(doc_id: str, doc_row, claims, db: Session) -> Response:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
        )
        from reportlab.lib import colors
    except ImportError:
        raise HTTPException(500, "reportlab is not installed; PDF export unavailable")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2*cm, rightMargin=2*cm)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph(f"CiteVerify Report – {doc_id}", styles["Title"]))
    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph(
        "<b>Automated analysis to assist human review. Not a final academic judgment.</b> "
        "⚠ All verdicts must be independently verified by a qualified reviewer.",
        styles["Normal"],
    ))
    story.append(Spacer(1, 0.5*cm))

    for cr in claims:
        claim = json.loads(cr.payload)
        story.append(Paragraph(
            f"<b>Claim:</b> {claim['text']}",
            styles["Normal"],
        ))
        verdicts = db.query(VerdictRow).filter(VerdictRow.claim_id == cr.claim_id).all()
        for vr in verdicts:
            v = json.loads(vr.payload)
            data = [
                ["Reference", v["reference_id"]],
                ["Verdict", v["verdict"].upper()],
                ["Confidence", f"{v['confidence']:.0%}"],
                ["Needs Human Review", "Yes" if v["needs_human_review"] else "No"],
                ["Flags", ", ".join(v.get("flags", [])) or "none"],
                ["Explanation", v["explanation"]],
            ]
            tbl = Table(data, colWidths=[4*cm, 13*cm])
            tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (0, -1), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ]))
            story.append(tbl)
        story.append(Spacer(1, 0.4*cm))

    doc.build(story)
    buf.seek(0)
    return Response(
        content=buf.read(),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=citeverify-{doc_id}.pdf"},
    )
