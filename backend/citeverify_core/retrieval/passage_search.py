"""
M2 – Passage search and quote location.

Public functions:
  search_passages(reference_id, query, k) -> list[Passage]
  locate_quote(reference_id, quote)       -> Evidence | None
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from ..common.schemas import Evidence, Passage
from .config import LOW_RETRIEVAL_THRESHOLD, QUOTE_FUZZY_THRESHOLD, INDEX_DIR
from .indexer import cosine_search

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# search_passages
# ---------------------------------------------------------------------------

def search_passages(reference_id: str, query: str, k: int = 5) -> list[Passage]:
    """Return up to *k* relevant passages for *query* from the indexed source.

    Adds "low_retrieval_score" flag metadata to the caller when the top score
    is below threshold (the flag itself is set by the caller in the Source / Verdict).

    Parameters
    ----------
    reference_id:
        Identifies the indexed source document.
    query:
        Free-text query (typically the claim text).
    k:
        Maximum number of passages to return.
    """
    hits = cosine_search(reference_id, query, k=k)
    passages: list[Passage] = []
    for chunk_meta, score in hits:
        p = Passage(
            passage_id=chunk_meta["chunk_id"],
            reference_id=reference_id,
            text=chunk_meta["text"],
            page=chunk_meta.get("page_index"),  # 0-based; UI converts to 1-based
            section=chunk_meta.get("section"),
            score=round(max(0.0, min(1.0, score)), 4),
        )
        passages.append(p)
    if not passages:
        logger.info("No passages found for reference %s (index may not exist)", reference_id)
    elif passages[0].score < LOW_RETRIEVAL_THRESHOLD:
        logger.info(
            "Low retrieval score (%.3f < %.3f) for reference %s",
            passages[0].score,
            LOW_RETRIEVAL_THRESHOLD,
            reference_id,
        )
    return passages


# ---------------------------------------------------------------------------
# locate_quote
# ---------------------------------------------------------------------------

def locate_quote(reference_id: str, quote: str) -> Evidence | None:
    """Find *quote* in the stored source text using fuzzy matching.

    For non-OCR sources, attempts to get PyMuPDF bboxes from the PDF.
    For OCR sources, returns empty bboxes (no coordinate data available).

    Returns None if the quote cannot be located above the threshold.
    """
    from rapidfuzz import fuzz, process

    index_dir = INDEX_DIR / reference_id
    meta_path = index_dir / "metadata.json"
    if not meta_path.exists():
        logger.warning("No index metadata for %s; cannot locate quote", reference_id)
        return None

    import json
    metadata: list[dict] = json.loads(meta_path.read_text(encoding="utf-8"))

    if not metadata:
        return None

    # Build a list of (passage_id, page, text) candidates
    candidates = [(m["chunk_id"], m.get("page_index"), m["text"], m.get("is_ocr", False)) for m in metadata]
    texts = [c[2] for c in candidates]

    # rapidfuzz process to find best chunk
    result = process.extractOne(quote, texts, scorer=fuzz.partial_ratio)
    if result is None:
        return None

    best_text, best_score, best_idx = result
    if best_score < QUOTE_FUZZY_THRESHOLD:
        logger.debug(
            "Quote fuzzy score %.1f < threshold %.1f for reference %s",
            best_score,
            QUOTE_FUZZY_THRESHOLD,
            reference_id,
        )
        return None

    chunk_id, page_index, _, is_ocr = candidates[best_idx]

    # Try to get a more precise quote substring
    matched_quote = _extract_best_window(quote, best_text)

    bboxes = []
    page_width: float | None = None
    page_height: float | None = None

    if not is_ocr:
        bboxes, page_width, page_height = _get_pdf_bboxes(reference_id, page_index, matched_quote)

    return Evidence(
        quote=matched_quote,
        passage_id=chunk_id,
        page=page_index,
        section=metadata[best_idx].get("section"),
        bboxes=bboxes,
        page_width=page_width,
        page_height=page_height,
    )


def _extract_best_window(query: str, text: str) -> str:
    """Return the substring of *text* that best matches *query*."""
    query_words = len(query.split())
    words = text.split()
    if len(words) <= query_words:
        return text
    best_score = -1.0
    best_window = text
    from rapidfuzz import fuzz
    step = max(1, query_words // 2)
    for i in range(0, max(1, len(words) - query_words + 1), step):
        window = " ".join(words[i : i + query_words])
        score = fuzz.ratio(query, window)
        if score > best_score:
            best_score = score
            best_window = window
    return best_window


def _get_pdf_bboxes(
    reference_id: str,
    page_index: int | None,
    quote: str,
) -> tuple[list, float | None, float | None]:
    """Return (bboxes, page_width, page_height) from PyMuPDF for *quote*.

    Returns empty list on any failure.
    """
    from .config import SOURCES_DIR
    from ..common.schemas import BBox

    if page_index is None:
        return [], None, None

    pdf_path = SOURCES_DIR / f"{reference_id}.pdf"
    if not pdf_path.exists():
        return [], None, None

    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(pdf_path))
        if page_index >= len(doc):
            doc.close()
            return [], None, None
        page = doc[page_index]
        page_width = float(page.rect.width)
        page_height = float(page.rect.height)
        # Search using PyMuPDF's text search (returns list of Rect)
        rects = page.search_for(quote[:200])  # search_for has length limits
        bboxes = [
            BBox(x0=float(r.x0), y0=float(r.y0), x1=float(r.x1), y1=float(r.y1))
            for r in rects
        ]
        doc.close()
        return bboxes, page_width, page_height
    except Exception as exc:
        logger.warning("PyMuPDF bbox extraction failed for %s page %d: %s", reference_id, page_index, exc)
        return [], None, None
