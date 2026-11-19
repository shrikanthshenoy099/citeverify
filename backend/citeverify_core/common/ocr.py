"""
common/ocr.py – OCR helper (owned by M1).

Primary engine : rapidocr-onnxruntime
Fallback engine: pytesseract (requires Tesseract binary on PATH)

If neither engine is available / succeeds, returns "" and callers MUST add
the "ocr_text" warning flag rather than crashing.
"""

from __future__ import annotations

import logging
import shutil

logger = logging.getLogger(__name__)


def ocr_pdf_page(pdf_path: str, page_index: int, dpi: int = 200) -> str:
    """
    Run OCR on a single PDF page and return the extracted text.

    Parameters
    ----------
    pdf_path:   Absolute or relative path to the PDF file.
    page_index: 0-based page index.
    dpi:        Rendering resolution (higher = better quality, slower).

    Returns
    -------
    Extracted text string, or "" if OCR is unavailable or fails.
    Callers must NOT crash on an empty return; add a warning flag instead.
    """
    # ── Try rapidocr-onnxruntime ────────────────────────────────────────────
    try:
        import fitz  # PyMuPDF
        from rapidocr_onnxruntime import RapidOCR

        doc = fitz.open(pdf_path)
        page = doc[page_index]
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("png")

        ocr = RapidOCR()
        result, _ = ocr(img_bytes)
        if result:
            return "\n".join(line[1] for line in result)
        return ""
    except ImportError:
        logger.debug("rapidocr-onnxruntime not available, trying pytesseract.")
    except Exception as exc:  # noqa: BLE001
        logger.warning("RapidOCR failed on %s page %d: %s", pdf_path, page_index, exc)

    # ── Fallback: pytesseract ───────────────────────────────────────────────
    if shutil.which("tesseract") is None:
        logger.warning("Tesseract binary not found; OCR unavailable.")
        return ""

    try:
        import fitz
        import pytesseract
        from PIL import Image
        import io

        doc = fitz.open(pdf_path)
        page = doc[page_index]
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        return pytesseract.image_to_string(img)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "pytesseract failed on %s page %d: %s", pdf_path, page_index, exc
        )
        return ""
