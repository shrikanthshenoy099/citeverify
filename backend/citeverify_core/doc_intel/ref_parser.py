"""
doc_intel/ref_parser.py – reference list extraction and parsing.

Strategy:
  1. Find the reference section in the raw document text using heuristics.
  2. Split individual entries with regex (numbered, author-year, dashes, etc.).
  3. For each entry run a regex pass to extract obvious fields (title, year, DOI).
  4. If regex is insufficient, call llm_client.complete_json for structured extraction.
  5. Assign parse_confidence based on how much was found by regex vs LLM.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Optional

from citeverify_core.common.schemas import Reference
from citeverify_core.doc_intel.config import (
    LLM_TEMPERATURE,
    REF_HIGH_CONFIDENCE,
    REF_LOW_CONFIDENCE,
    REF_OCR_CONFIDENCE_PENALTY,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Heuristic headers that mark the start of a reference section.
_REF_HEADER_RE = re.compile(
    r"(?im)^[\s]*(?:references?|bibliography|works\s+cited|literature\s+cited)"
    r"\s*[\:\.]?\s*$"
)

# Numbered entries: [1], (1), 1.
_NUMBERED_SPLIT_RE = re.compile(r"(?m)(?:^|\n)(?:\[(\d+)\]|\((\d+)\)|(\d+)[\.\)])\s+")

# Author-year style: "Surname, F. (" followed by a 4-digit year.
_AUTHORYEAR_SPLIT_RE = re.compile(r"(?m)\n(?=[A-Z][a-zA-Zéàüö\-']+,\s+[A-Z])")

# DOI extractor
_DOI_RE = re.compile(r"\b(?:doi[:\s]*|https?://doi\.org/)([^\s,;\"\']+)", re.IGNORECASE)

# Year extractor (4-digit 1800–2099)
_YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")

# Title – text between first '" ... "' or italic heuristic (not always reliable)
_QUOTED_TITLE_RE = re.compile(r'["\u201c](.{10,200}?)["\u201d]')


# ---------------------------------------------------------------------------
# LLM schema for structured reference extraction
# ---------------------------------------------------------------------------

_REF_EXTRACTION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "title": {"type": ["string", "null"]},
        "authors": {"type": "array", "items": {"type": "string"}},
        "year": {"type": ["integer", "null"]},
        "doi": {"type": ["string", "null"]},
        "venue": {"type": ["string", "null"]},
    },
    "required": ["title", "authors", "year", "doi", "venue"],
}

_REF_SYSTEM_PROMPT = (
    "You are a bibliographic metadata extractor. "
    "Given a raw reference string, extract the fields as JSON. "
    "Return null for missing fields. Authors as list of full names."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_doi(text: str) -> Optional[str]:
    m = _DOI_RE.search(text)
    return m.group(1).rstrip(".,;)") if m else None


def _extract_year(text: str) -> Optional[int]:
    years = _YEAR_RE.findall(text)
    return int(years[-1]) if years else None


def _extract_quoted_title(text: str) -> Optional[str]:
    m = _QUOTED_TITLE_RE.search(text)
    return m.group(1).strip() if m else None


def _split_reference_section(text: str) -> list[str]:
    """
    Split raw reference section text into individual entry strings.
    Returns a flat list of raw entry strings (may still need trimming).
    """
    # Try numbered first (most common in scientific papers)
    matches = list(_NUMBERED_SPLIT_RE.finditer(text))
    if len(matches) >= 2:
        entries: list[str] = []
        for i, m in enumerate(matches):
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            entries.append(text[start:end].strip())
        return [e for e in entries if e]

    # Try author-year style
    parts = _AUTHORYEAR_SPLIT_RE.split(text)
    if len(parts) >= 2:
        return [p.strip() for p in parts if p.strip()]

    # Fallback: split on double newlines
    parts = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    return parts


def _locate_reference_section(full_text: str) -> Optional[str]:
    """
    Return the substring of full_text that is likely the reference section,
    or None if not found.
    """
    m = _REF_HEADER_RE.search(full_text)
    if not m:
        return None
    # Take everything after the header; cap at 15 000 chars to avoid huge LLM calls.
    return full_text[m.end() :].strip()[:15_000]


def _llm_enrich(raw_text: str) -> dict:
    """
    Call the LLM to extract structured fields from a raw reference string.
    Returns a dict with keys matching _REF_EXTRACTION_SCHEMA; empty dict on failure.
    """
    try:
        from citeverify_core.common import llm_client  # lazy import avoids jsonschema at module load
        result = llm_client.complete_json(
            system=_REF_SYSTEM_PROMPT,
            user=f"Reference string:\n{raw_text}",
            schema=_REF_EXTRACTION_SCHEMA,
            temperature=LLM_TEMPERATURE,
        )
        return result if isinstance(result, dict) else {}
    except Exception as exc:
        logger.warning("LLM reference enrichment failed: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_references(
    full_text: str,
    doc_id: str,
    ocr_page_indices: frozenset[int] | None = None,
) -> list[Reference]:
    """
    Extract and parse references from document text.

    Parameters
    ----------
    full_text:
        Complete document text (all pages concatenated, with page markers).
    doc_id:
        Document identifier (used for unique reference IDs).
    ocr_page_indices:
        Set of page indices whose text came from OCR, to lower confidence.

    Returns
    -------
    list[Reference]
        Parsed references.  May be empty if no reference section found.
    """
    ocr_pages = ocr_page_indices or frozenset()

    ref_section = _locate_reference_section(full_text)
    if ref_section is None:
        logger.info("[M1] No reference section found in doc %s.", doc_id)
        return []

    raw_entries = _split_reference_section(ref_section)
    logger.info("[M1] Found %d raw reference entries in doc %s.", len(raw_entries), doc_id)

    references: list[Reference] = []
    for idx, raw in enumerate(raw_entries):
        if len(raw) < 10:
            continue

        ref_id = f"{doc_id}_ref_{idx:04d}"

        # Quick regex pass
        doi = _extract_doi(raw)
        year = _extract_year(raw)
        title = _extract_quoted_title(raw)

        regex_found_fields = sum(x is not None for x in [doi, year, title])
        # If regex found all three major fields skip LLM to save quota
        authors: list[str] = []
        venue: Optional[str] = None
        llm_used = False

        if regex_found_fields < 2:
            enriched = _llm_enrich(raw)
            if enriched:
                llm_used = True
                title = title or enriched.get("title")
                year = year or enriched.get("year")
                doi = doi or enriched.get("doi")
                authors = enriched.get("authors") or []
                venue = enriched.get("venue")

        # Confidence scoring
        fields_found = sum(x is not None for x in [title, year, doi])
        if fields_found >= 3:
            confidence = REF_HIGH_CONFIDENCE
        elif fields_found >= 1:
            # regex was partly uncertain
            confidence = (REF_HIGH_CONFIDENCE + REF_LOW_CONFIDENCE) / 2
        else:
            confidence = REF_LOW_CONFIDENCE

        # Penalize entries whose text came from OCR
        # We approximate: if any OCR page, reduce confidence uniformly.
        # (We don't know which page each ref is on at this stage.)
        if ocr_pages:
            confidence = max(0.0, confidence - REF_OCR_CONFIDENCE_PENALTY)

        references.append(
            Reference(
                reference_id=ref_id,
                raw_text=raw,
                title=title,
                authors=authors,
                year=year,
                doi=doi,
                venue=venue,
                parse_confidence=round(confidence, 3),
            )
        )

    return references
