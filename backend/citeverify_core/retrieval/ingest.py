"""
M2 – ingest_pdf: build a Source + index from a reviewer-supplied PDF.

This is the entry point for POST /api/references/{reference_id}/source.
"""
from __future__ import annotations

import logging
from pathlib import Path

from ..common.schemas import Source
from .chunker import build_chunks
from .indexer import build_index
from .pdf_handler import extract_pages

logger = logging.getLogger(__name__)


def ingest_pdf(reference_id: str, pdf_path: str) -> Source:
    """Index a reviewer-supplied PDF and return a Source record.

    - Extracts text (with OCR fallback for image-only pages).
    - Builds and saves the embedding index.
    - Sets flag ``manual_source`` and ``text_level="full_text"``.
    - Any OCR pages additionally get the ``ocr_text`` flag.

    Parameters
    ----------
    reference_id:
        The reference this PDF belongs to.
    pdf_path:
        Absolute (or resolvable) path to the PDF file.

    Returns
    -------
    Source
        A Source record with text_level="full_text" and manual_source flag.
        Does NOT attempt to look up metadata from external databases – callers
        (M4 orchestrator) should merge in existing Reference metadata.
    """
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"ingest_pdf: PDF not found: {pdf_path}")

    # --- Extract text ---
    pages = extract_pages(path, reference_id)

    has_ocr = any(p.is_ocr for p in pages)
    has_text = any(p.text.strip() for p in pages)

    # --- Build chunks and index ---
    chunks = build_chunks(pages, reference_id)
    if chunks:
        build_index(chunks, reference_id)
        text_level = "full_text"
    else:
        logger.warning("ingest_pdf: no text extracted from %s; index not built.", pdf_path)
        text_level = "none"

    # --- Flags ---
    flags: list[str] = ["manual_source"]
    if has_ocr:
        flags.append("ocr_text")

    source = Source(
        reference_id=reference_id,
        matched=True,          # reviewer supplied it, so we treat it as confirmed
        match_score=1.0,
        title="",              # M4 / caller fills this from the existing Reference
        authors=[],
        year=None,
        doi=None,
        url=None,
        pdf_path=str(path),
        text_level=text_level,  # type: ignore[arg-type]
        full_text_available=(text_level == "full_text"),
        source_database="manual_upload",
        flags=flags,
    )
    logger.info(
        "ingest_pdf complete for %s: %d pages, %d chunks, flags=%s",
        reference_id,
        len(pages),
        len(chunks),
        flags,
    )
    return source
