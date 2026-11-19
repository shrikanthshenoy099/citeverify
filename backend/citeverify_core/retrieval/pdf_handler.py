"""
M2 – PDF download and text extraction.

Responsibilities:
  - Download a PDF from a URL and save it under data/sources/{reference_id}.pdf
  - Validate the file is a real PDF (magic bytes check) and within size limit.
  - Extract text page-by-page using PyMuPDF (fitz).
  - Fall back to OCR (via common/ocr.py) for pages that return no text.
  - Return a list of PageText(page_index, text, is_ocr) tuples.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import NamedTuple

from .config import HTTP_TIMEOUT, PDF_MAX_BYTES, SOURCES_DIR
from .http_client import get_session

logger = logging.getLogger(__name__)

_PDF_MAGIC = b"%PDF"
_USER_AGENT = "CiteVerify/1.0 (academic citation checker; mailto:citeverify@example.com)"


class PageText(NamedTuple):
    page_index: int   # 0-based
    text: str
    is_ocr: bool


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_pdf(url: str, reference_id: str) -> Path | None:
    """Download *url* and save to data/sources/{reference_id}.pdf.

    Validates:
      - HTTP 200 response with Content-Type application/pdf or .pdf extension.
      - File starts with ``%PDF`` magic bytes.
      - File size does not exceed PDF_MAX_BYTES (default 50 MB).

    Returns the local path, or None on any failure.  Never raises.
    """
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    dest = SOURCES_DIR / f"{reference_id}.pdf"
    if dest.exists():
        # Quick magic-byte sanity check on cached file
        if _is_valid_pdf(dest):
            logger.debug("PDF already cached: %s", dest)
            return dest
        else:
            logger.warning("Cached PDF %s failed magic-byte check; re-downloading.", dest)
            dest.unlink(missing_ok=True)

    session = get_session()
    headers = {"User-Agent": _USER_AGENT}
    try:
        resp = session.get(url, timeout=HTTP_TIMEOUT, stream=True, headers=headers)
        resp.raise_for_status()

        # Content-Type sanity (not fatal – some servers lie)
        ct = resp.headers.get("Content-Type", "")
        if ct and "html" in ct.lower():
            logger.warning("PDF URL %s returned HTML (possible paywall/login page); skipping.", url)
            return None

        # Stream to disk with size limit
        bytes_written = 0
        with dest.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=65536):
                bytes_written += len(chunk)
                if bytes_written > PDF_MAX_BYTES:
                    logger.warning(
                        "PDF for %s exceeds size limit (%d bytes); aborting download.",
                        reference_id, PDF_MAX_BYTES,
                    )
                    fh.close()
                    dest.unlink(missing_ok=True)
                    return None
                fh.write(chunk)

        # Magic-byte validation
        if not _is_valid_pdf(dest):
            logger.warning("Downloaded file for %s is not a valid PDF (bad magic bytes).", reference_id)
            dest.unlink(missing_ok=True)
            return None

        logger.info("Downloaded PDF for %s -> %s (%d bytes)", reference_id, dest, bytes_written)
        return dest

    except Exception as exc:
        logger.warning("PDF download failed for %s: %s", reference_id, exc)
        if dest.exists():
            dest.unlink(missing_ok=True)
        return None


def _is_valid_pdf(path: Path) -> bool:
    """Return True if *path* starts with the PDF magic bytes ``%PDF``."""
    try:
        with path.open("rb") as fh:
            return fh.read(4) == _PDF_MAGIC
    except Exception:
        return False


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
