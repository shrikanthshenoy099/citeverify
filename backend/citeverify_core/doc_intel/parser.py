"""
doc_intel/parser.py – public M1 entry point.

parse_document(file_path, raw_text, doc_id) -> ParsedDocument

Supports:
  - PDF  (via PyMuPDF; OCR on low-text pages)
  - DOCX (via python-docx)
  - Pasted text (plain string)
"""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Optional

import pysbd  # type: ignore

from citeverify_core.common.schemas import ParsedDocument
from citeverify_core.doc_intel.claim_extractor import extract_claims
from citeverify_core.doc_intel.config import (
    OCR_DPI,
    OCR_MAX_PAGES,
    OCR_MIN_CHARS_THRESHOLD,
)
from citeverify_core.doc_intel.ref_parser import parse_references

logger = logging.getLogger(__name__)

_segmenter = pysbd.Segmenter(language="en", clean=False)

# Marker inserted between pages so we can track char offsets per page.
_PAGE_SEP = "\n\f\n"  # form-feed


# ---------------------------------------------------------------------------
# Text extraction helpers
# ---------------------------------------------------------------------------

def _extract_text_pdf(file_path: Path) -> tuple[str, list[int], list[str], frozenset[int]]:
    """
    Extract text from a PDF using PyMuPDF, falling back to OCR on sparse pages.

    Returns
    -------
    full_text:
        All page texts concatenated with _PAGE_SEP.
    page_char_starts:
        char offset where each page begins in full_text (len == num_pages).
    warnings:
        List of warning strings.
    ocr_page_indices:
        0-based indices of pages whose text came from OCR.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise ImportError("PyMuPDF (fitz) is required for PDF parsing.") from exc

    from citeverify_core.common.ocr import ocr_pdf_page

    doc = fitz.open(str(file_path))
    num_pages = len(doc)
    pages_text: list[str] = []
    page_char_starts: list[int] = []
    warnings: list[str] = []
    ocr_page_indices: set[int] = set()
    ocr_pages_used: list[int] = []
    skipped_ocr_pages: list[int] = []

    running_offset = 0
    for i in range(num_pages):
        page = doc[i]
        text = page.get_text("text")

        if len(text.strip()) < OCR_MIN_CHARS_THRESHOLD:
            if i < OCR_MAX_PAGES:
                ocr_text = ocr_pdf_page(str(file_path), i, dpi=OCR_DPI)
                if ocr_text:
                    text = ocr_text
                    ocr_page_indices.add(i)
                    ocr_pages_used.append(i + 1)  # 1-based for warnings
                else:
                    # OCR returned nothing – flag but keep empty string
                    skipped_ocr_pages.append(i + 1)
            else:
                skipped_ocr_pages.append(i + 1)

        page_char_starts.append(running_offset)
        pages_text.append(text)
        running_offset += len(text) + len(_PAGE_SEP)

    doc.close()

    if ocr_pages_used:
        warnings.append(f"ocr_used_pages:{ocr_pages_used}")

    if skipped_ocr_pages:
        # Either cap was reached or OCR was unavailable
        # Distinguish: if ALL skipped are beyond OCR_MAX_PAGES, it's a cap warning.
        over_limit = [p for p in skipped_ocr_pages if p > OCR_MAX_PAGES]
        below_limit = [p for p in skipped_ocr_pages if p <= OCR_MAX_PAGES]
        if below_limit:
            warnings.append("scanned_pdf_ocr_unavailable")
        if over_limit:
            warnings.append(
                f"ocr_cap_reached:pages_beyond_{OCR_MAX_PAGES}_not_processed:{over_limit}"
            )

    full_text = _PAGE_SEP.join(pages_text)
    return full_text, page_char_starts, warnings, frozenset(ocr_page_indices)


def _extract_text_docx(file_path: Path) -> tuple[str, list[str]]:
    """
    Extract text from a DOCX file.  Returns (full_text, warnings).
    Pages are not tracked (page = null per spec).
    """
    try:
        import docx  # python-docx
    except ImportError as exc:
        raise ImportError("python-docx is required for DOCX parsing.") from exc

    document = docx.Document(str(file_path))
    paragraphs: list[str] = []
    for para in document.paragraphs:
        t = para.text.strip()
        if t:
            paragraphs.append(t)
    # Also include table cell text
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                t = cell.text.strip()
                if t:
                    paragraphs.append(t)
    return "\n".join(paragraphs), []


# ---------------------------------------------------------------------------
# Section heading detection
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(
    r"(?im)^\s*(?:\d+\.?\s+)?[A-Z][A-Z\s\:\-]{3,60}\s*$"
)


def _build_section_map(sentences: list[str], full_text: str, offsets: list[tuple[int, int]]) -> list[Optional[str]]:
    """
    For each sentence, find the most recent section heading that precedes it.
    Very lightweight: looks for all-caps or title-case short lines.
    """
    headings: list[tuple[int, str]] = []
    for m in _HEADING_RE.finditer(full_text):
        headings.append((m.start(), m.group().strip()))

    result: list[Optional[str]] = []
    for start, _end in offsets:
        # Find the last heading whose offset <= sentence start
        current: Optional[str] = None
        for h_start, h_text in reversed(headings):
            if h_start <= start:
                current = h_text
                break
        result.append(current)
    return result


# ---------------------------------------------------------------------------
# Page map builder
# ---------------------------------------------------------------------------

def _build_page_map(
    sentences: list[str],
    offsets: list[tuple[int, int]],
    page_char_starts: list[int],
) -> list[Optional[int]]:
    """
    For each sentence return its 1-based page number, or None if no page info.
    """
    if not page_char_starts:
        return [None] * len(sentences)

    result: list[Optional[int]] = []
    for start, _end in offsets:
        page = None
        for p_idx, p_start in enumerate(page_char_starts):
            if start >= p_start:
                page = p_idx + 1  # 1-based
            else:
                break
        result.append(page)
    return result


# ---------------------------------------------------------------------------
# Sentence segmentation with offset tracking
# ---------------------------------------------------------------------------

def _segment_with_offsets(full_text: str) -> tuple[list[str], list[tuple[int, int]]]:
    """
    Run pysbd and compute (char_start, char_end) for each sentence in full_text.
    pysbd does not return offsets directly, so we re-locate each sentence.
    """
    sentences = _segmenter.segment(full_text)
    offsets: list[tuple[int, int]] = []
    cursor = 0
    for sent in sentences:
        idx = full_text.find(sent, cursor)
        if idx == -1:
            idx = cursor  # fallback: shouldn't happen
        offsets.append((idx, idx + len(sent)))
        cursor = idx + len(sent)
    return sentences, offsets


# ---------------------------------------------------------------------------
# Citation-marker → reference_id index builder
# ---------------------------------------------------------------------------

def _build_ref_index(references: list, full_text: str) -> dict[str, str]:
    """
    Build a simple marker -> reference_id mapping.

    For numbered references: maps "[N]" or "(N)" to the Nth reference.
    For author-year: tries to match author surname + year substrings.
    This is a best-effort pass; unresolved markers are left with no_citation flag.
    """
    index: dict[str, str] = {}
    for i, ref in enumerate(references):
        # Numeric markers
        n = i + 1
        for fmt in (f"[{n}]", f"({n})"):
            index[fmt] = ref.reference_id

        # Author-year marker: "FirstAuthorSurname YYYY"
        if ref.authors and ref.year:
            surname = ref.authors[0].split(",")[0].strip().split()[-1]
            index[f"({surname} {ref.year})"] = ref.reference_id
            index[f"({surname} et al., {ref.year})"] = ref.reference_id
            index[f"({surname} et al. {ref.year})"] = ref.reference_id

    return index


# ---------------------------------------------------------------------------
# OCR sentence index builder
# ---------------------------------------------------------------------------

def _build_ocr_sentence_set(
    offsets: list[tuple[int, int]],
    page_char_starts: list[int],
    ocr_page_indices: frozenset[int],
    page_texts: list[str] | None,
) -> frozenset[int]:
    """
    Map OCR page indices to sentence indices using character offsets.
    """
    if not ocr_page_indices or not page_char_starts:
        return frozenset()
    ocr_sentences: set[int] = set()
    for s_idx, (start, _end) in enumerate(offsets):
        for p_idx, p_start in enumerate(page_char_starts):
            # Determine end of this page's character range
            p_end = page_char_starts[p_idx + 1] if p_idx + 1 < len(page_char_starts) else float("inf")
            if p_start <= start < p_end and p_idx in ocr_page_indices:
                ocr_sentences.add(s_idx)
                break
    return frozenset(ocr_sentences)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_document(
    file_path: Optional[str],
    raw_text: Optional[str],
    doc_id: str,
) -> ParsedDocument:
    """
    Parse an academic document and return structured claims and references.

    Parameters
    ----------
    file_path:
        Path to the uploaded file (.pdf or .docx).  Mutually exclusive with raw_text.
    raw_text:
        Pre-supplied plain text.  Used when file_path is None.
    doc_id:
        Unique document identifier (assigned by the caller).

    Returns
    -------
    ParsedDocument
        Contains claims, references and any processing warnings.

    Notes
    -----
    - PDF: page numbers are tracked (1-based).
    - DOCX / pasted text: page = null for all claims.
    - For PDF pages with < OCR_MIN_CHARS_THRESHOLD characters, OCR is attempted.
    - OCR is capped at the first OCR_MAX_PAGES pages.
    """
    warnings: list[str] = []
    source_type: str
    full_text: str
    page_char_starts: list[int] = []
    ocr_page_indices: frozenset[int] = frozenset()
    num_pages: Optional[int] = None

    # ------------------------------------------------------------------
    # 1. Ingest
    # ------------------------------------------------------------------
    if file_path is not None:
        path = Path(file_path)
        suffix = path.suffix.lower()

        if suffix == ".pdf":
            source_type = "pdf"
            try:
                full_text, page_char_starts, ocr_warnings, ocr_page_indices = _extract_text_pdf(path)
                warnings.extend(ocr_warnings)
                # Count pages from page_char_starts
                num_pages = len(page_char_starts)
            except Exception as exc:
                logger.error("[M1] PDF extraction failed for %s: %s", file_path, exc)
                warnings.append(f"pdf_extraction_error:{exc}")
                return ParsedDocument(
                    doc_id=doc_id,
                    source_type="pdf",
                    num_pages=None,
                    references=[],
                    claims=[],
                    warnings=warnings,
                )
        elif suffix in (".docx", ".doc"):
            source_type = "docx"
            try:
                full_text, docx_warnings = _extract_text_docx(path)
                warnings.extend(docx_warnings)
            except Exception as exc:
                logger.error("[M1] DOCX extraction failed for %s: %s", file_path, exc)
                warnings.append(f"docx_extraction_error:{exc}")
                return ParsedDocument(
                    doc_id=doc_id,
                    source_type="docx",
                    num_pages=None,
                    references=[],
                    claims=[],
                    warnings=warnings,
                )
        else:
            warnings.append(f"unsupported_file_type:{suffix}")
            logger.warning("[M1] Unsupported file type %s for doc %s.", suffix, doc_id)
            return ParsedDocument(
                doc_id=doc_id,
                source_type="text",
                num_pages=None,
                references=[],
                claims=[],
                warnings=warnings,
            )
    elif raw_text is not None:
        source_type = "text"
        full_text = raw_text
    else:
        raise ValueError("parse_document: either file_path or raw_text must be provided.")

    # ------------------------------------------------------------------
    # 2. Sentence segmentation
    # ------------------------------------------------------------------
    try:
        sentences, offsets = _segment_with_offsets(full_text)
    except Exception as exc:
        logger.error("[M1] Sentence segmentation failed: %s", exc)
        warnings.append(f"segmentation_error:{exc}")
        return ParsedDocument(
            doc_id=doc_id,
            source_type=source_type,
            num_pages=num_pages,
            references=[],
            claims=[],
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # 3. Reference extraction
    # ------------------------------------------------------------------
    references = parse_references(full_text, doc_id, ocr_page_indices=ocr_page_indices)
    if not references:
        warnings.append("no_references_found")

    # ------------------------------------------------------------------
    # 4. Build maps
    # ------------------------------------------------------------------
    page_map = _build_page_map(sentences, offsets, page_char_starts)
    section_map = _build_section_map(sentences, full_text, offsets)
    ref_index = _build_ref_index(references, full_text)
    ocr_sent_set = _build_ocr_sentence_set(offsets, page_char_starts, ocr_page_indices, None)

    # ------------------------------------------------------------------
    # 5. Claim extraction
    # ------------------------------------------------------------------
    claims = extract_claims(
        sentences=sentences,
        char_offsets=offsets,
        page_map=page_map,
        section_map=section_map,
        ref_index=ref_index,
        doc_id=doc_id,
        ocr_sentence_indices=ocr_sent_set,
    )

    logger.info(
        "[M1] doc=%s type=%s pages=%s refs=%d claims=%d warnings=%d",
        doc_id,
        source_type,
        num_pages,
        len(references),
        len(claims),
        len(warnings),
    )

    return ParsedDocument(
        doc_id=doc_id,
        source_type=source_type,
        num_pages=num_pages,
        references=references,
        claims=claims,
        warnings=warnings,
    )
