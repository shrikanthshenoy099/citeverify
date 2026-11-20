"""
app/routers/sources.py – Source-related endpoints.

GET  /api/sources/{reference_id}/pdf
POST /api/references/{reference_id}/source   – manual PDF upload
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import cast

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import ReferenceRow, SourceRow
from app.db.session import get_db

logger = logging.getLogger(__name__)

router_sources = APIRouter(prefix="/api/sources", tags=["sources"])
router_references = APIRouter(prefix="/api/references", tags=["references"])


# ---------------------------------------------------------------------------
# GET /api/sources/{reference_id}/pdf
# ---------------------------------------------------------------------------

@router_sources.get("/{reference_id}/pdf")
def get_source_pdf(reference_id: str, db: Session = Depends(get_db)):
    """Return the locally stored PDF for a source, or 404."""
    source_row = db.get(SourceRow, reference_id)
    if source_row is None:
        raise HTTPException(404, f"Source {reference_id!r} not found")

    raw_payload = cast(str, source_row.payload)
    source = json.loads(raw_payload)
    pdf_path = source.get("pdf_path")
    if not pdf_path or not Path(pdf_path).is_file():
        raise HTTPException(404, "PDF not available for this source")
    return FileResponse(pdf_path, media_type="application/pdf")


# ---------------------------------------------------------------------------
# POST /api/references/{reference_id}/source
# ---------------------------------------------------------------------------

@router_references.post("/{reference_id}/source", status_code=202)
async def upload_manual_source(
    reference_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    file: UploadFile = File(...),
):
    """
    Accept a manually uploaded PDF for a reference.
    Calls M2.ingest_pdf() then re-runs verify() for every claim citing this reference.

    Returns immediately (202); processing continues in the background.
    """
    ref_row = db.get(ReferenceRow, reference_id)
    if ref_row is None:
        raise HTTPException(404, f"Reference {reference_id!r} not found")

    fname = file.filename or "source.pdf"
    if not fname.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are accepted")

    content = await file.read()
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(413, f"File exceeds {settings.max_upload_bytes // (1024*1024)} MB limit")

    dest = settings.sources_dir / reference_id
    dest.mkdir(parents=True, exist_ok=True)
    dest_file = dest / fname
    dest_file.write_bytes(content)

    background_tasks.add_task(
        _ingest_and_reverify,
        reference_id=reference_id,
        pdf_path=str(dest_file),
    )
    logger.info("Manual source PDF queued for reference %s", reference_id)
    return {"reference_id": reference_id, "status": "processing"}


def _ingest_and_reverify(reference_id: str, pdf_path: str) -> None:
    """Background task: ingest PDF, update source, re-verify claims."""
    from app.db.session import SessionLocal
    from app.orchestrator import reverify_reference

    db = SessionLocal()
    try:
        try:
            if settings.use_mocks:
                from citeverify_core.common.schemas import Flags, Reference
                from app.mocks import mock_retrieve_source

                ref_row = db.get(ReferenceRow, reference_id)
                if ref_row:
                    raw_ref_payload = cast(str, ref_row.payload)
                    ref = Reference(**json.loads(raw_ref_payload))
                    source = mock_retrieve_source(ref)
                    source.pdf_path = pdf_path
                    source.text_level = "full_text"
                    source.full_text_available = True
                    source.flags = [f for f in source.flags if f != "full_text_unavailable"]
                    if Flags.MANUAL_SOURCE not in source.flags:
                        source.flags.append(Flags.MANUAL_SOURCE)
                    _upsert_source(db, source)
            else:
                from citeverify_core.retrieval import ingest_pdf  # type: ignore[import]

                source = ingest_pdf(reference_id=reference_id, pdf_path=pdf_path)
                _upsert_source(db, source)
        except Exception as exc:
            logger.exception("ingest_pdf failed for reference %s: %s", reference_id, exc)
            return

        reverify_reference(reference_id=reference_id, db=db)
    finally:
        db.close()


def _upsert_source(db: Session, source) -> None:
    existing = db.get(SourceRow, source.reference_id)
    payload_json = source.model_dump_json()
    if existing is None:
        db.add(SourceRow(reference_id=source.reference_id, payload=payload_json))
    else:
        setattr(existing, "payload", payload_json)
    db.commit()