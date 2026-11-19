"""
M2 – PDF download and text extraction.

Responsibilities:
  - Download a PDF from a URL and save it under data/sources/{reference_id}.pdf
  - Extract text page-by-page using PyMuPDF (fitz).
  - Fall back to OCR (via common/ocr.py) for pages that return no text.
  - Return a list of (page_index: int, text: str, is_ocr: bool) tuples.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import NamedTuple

from .config import HTTP_TIMEOUT, SOURCES_DIR
from .http_client import get_session

logger = logging.getLogger(__name__)


class PageText(NamedTuple):
    page_index: int   # 0-based
    text: str
    is_ocr: bool


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_pdf(url: str, reference_id: str) -> Path | None:
    """Download *url* and save to data/sources/{reference_id}.pdf.

    Returns the local path, or None on failure.
    """
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    dest = SOURCES_DIR / f"{reference_id}.pdf"
    if dest.exists():
        logger.debug("PDF already cached: %s", dest)
        return dest

    session = get_session()
    try:
        resp = session.get(url, timeout=HTTP_TIMEOUT, stream=True)
        resp.raise_for_status()
        with dest.open("wb") as fh:
            shutil.copyfileobj(resp.raw, fh)
        logger.info("Downloaded PDF for %s -> %s", reference_id, dest)
        return dest
    except Exception as exc:
        logger.warning("PDF download failed for %s: %s", reference_id, exc)
        if dest.exists():
            dest.unlink(missing_ok=True)
        return None


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def extract_pages(pdf_path: Path, reference_id: str) -> list[PageText]:
    """Return per-page text from *pdf_path*, falling back to OCR when needed.

    Parameters
    ----------
    pdf_path:
        Absolute path to the PDF file.
    reference_id:
        Used when calling OCR helpers (for logging / warnings).
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.error("PyMuPDF (fitz) is not installed; cannot extract PDF text.")
        return []

    pages: list[PageText] = []
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as exc:
        logger.error("Cannot open PDF %s: %s", pdf_path, exc)
        return []

    for page_index in range(len(doc)):
        try:
            page = doc[page_index]
            text = page.get_text("text")  # type: ignore[attr-defined]
        except Exception as exc:
            logger.warning("Page %d text extraction failed (%s): %s", page_index, pdf_path, exc)
            text = ""

        is_ocr = False
        if not text.strip():
            # Fall back to OCR
            text = _ocr_page(str(pdf_path), page_index, reference_id)
            is_ocr = bool(text.strip())

        pages.append(PageText(page_index=page_index, text=text, is_ocr=is_ocr))

    doc.close()
    return pages


def _ocr_page(pdf_path: str, page_index: int, reference_id: str) -> str:
    """Call common/ocr.py's ocr_pdf_page; return "" if unavailable."""
    try:
        from citeverify_core.common.ocr import ocr_pdf_page  # M1 delivers this
        return ocr_pdf_page(pdf_path, page_index)
    except ImportError:
        logger.debug("common.ocr not yet available; OCR skipped for page %d of %s", page_index, reference_id)
        return ""
    except Exception as exc:
        logger.warning("OCR failed for page %d of %s: %s", page_index, reference_id, exc)
        return ""
