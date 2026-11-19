"""
doc_intel/claim_extractor.py – sentence-level claim extraction.

Uses pysbd for sentence segmentation.  For each sentence decides:
  - Is it a checkable claim? (heuristics + optionally LLM)
  - What claim type is it?
  - What citation markers does it carry?
  - Which reference IDs (by marker) does it link to?
  - What numbers does it mention?
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Optional

from citeverify_core.common.schemas import Claim, ClaimType, Flags, Reference
from citeverify_core.doc_intel.config import CLAIM_MIN_CHARS, CONTEXT_SENTENCES

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Citation marker patterns
# ---------------------------------------------------------------------------

# Numeric markers: [1], [1,2], [1-3], [1, 2, 3], (1), (1,2)
_NUMERIC_MARKER_RE = re.compile(
    r"(?:\[(?:\d+(?:[,\-]\s*\d+)*)\]|\((?:\d+(?:[,\-]\s*\d+)*)\))"
)

# Author-year markers: (Smith 2020), (Smith et al., 2020), (Smith & Jones, 2020)
_AUTHORYEAR_MARKER_RE = re.compile(
    r"\([A-Z][a-zA-Zéàüö'\-]+(?: et al\.?)?"
    r"(?:,?\s*(?:&|and)\s+[A-Z][a-zA-Zéàüö'\-]+)?"
    r",?\s*\d{4}[a-z]?\)"
)

# Numbers mentioned in a sentence (decimals, percentages, ranges)
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?(?:\s*%)?")

# ---------------------------------------------------------------------------
# Claim-type heuristics
# ---------------------------------------------------------------------------

_NUMERIC_SIGNALS = re.compile(
    r"\b(?:increased?|decreased?|reduced?|improved?|higher|lower|greater|less|"
    r"factor|fold|percent|percentage|ratio|rate|score|accuracy|precision|recall|"
    r"sensitivity|specificity)\b",
    re.IGNORECASE,
)
_CONCLUSION_SIGNALS = re.compile(
    r"\b(?:therefore|thus|hence|conclude[sd]?|conclude[sd]?\s+that|"
    r"suggest[s]?\s+that|demonstrat\w+|show[sn]?\s+that|indicat\w+)\b",
    re.IGNORECASE,
)
_METHODOLOGICAL_SIGNALS = re.compile(
    r"\b(?:method|approach|algorithm|technique|model|framework|architecture|"
    r"protocol|procedure|experiment|dataset|corpus|benchmark|baseline|"
    r"implement\w+|train\w+|evaluat\w+)\b",
    re.IGNORECASE,
)


def _classify_claim(text: str) -> ClaimType:
    nums = _NUMBER_RE.findall(text)
    if len(nums) >= 1 and _NUMERIC_SIGNALS.search(text):
        return "numeric"
    if _CONCLUSION_SIGNALS.search(text):
        return "conclusion"
    if _METHODOLOGICAL_SIGNALS.search(text):
        return "methodological"
    return "factual"


def _extract_citation_markers(text: str) -> list[str]:
    markers: list[str] = []
    markers += _NUMERIC_MARKER_RE.findall(text)
    markers += _AUTHORYEAR_MARKER_RE.findall(text)
    return list(dict.fromkeys(markers))  # deduplicate, preserve order


def _markers_to_ref_ids(markers: list[str], ref_index: dict[str, str]) -> list[str]:
    """
    Map citation markers to reference IDs using the index built by parse_document.

    ref_index: maps marker string -> reference_id
    """
    ids: list[str] = []
    for m in markers:
        rid = ref_index.get(m)
        if rid:
            ids.append(rid)
    return list(dict.fromkeys(ids))


def _is_checkable(sentence: str) -> bool:
    """Very lightweight filter: skip very short, header-like, or list-only sentences."""
    s = sentence.strip()
    if len(s) < CLAIM_MIN_CHARS:
        return False
    # Skip lines that look like headings (no verb, end with no punctuation)
    if re.match(r"^[A-Z][A-Za-z\s]{0,60}$", s):
        return False
    # Skip pure URL lines
    if re.match(r"^https?://\S+$", s):
        return False
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_claims(
    sentences: list[str],
    char_offsets: list[tuple[int, int]],
    page_map: list[Optional[int]],
    section_map: list[Optional[str]],
    ref_index: dict[str, str],
    doc_id: str,
    ocr_sentence_indices: frozenset[int] | None = None,
) -> list[Claim]:
    """
    Convert a list of sentences into Claim objects.

    Parameters
    ----------
    sentences:
        All sentences from the document in order.
    char_offsets:
        (char_start, char_end) for each sentence in the full text.
    page_map:
        Page number (1-based, or None) for each sentence.
    section_map:
        Section heading (or None) for each sentence.
    ref_index:
        Maps citation-marker string -> reference_id.
    doc_id:
        Document identifier used to build claim_id.
    ocr_sentence_indices:
        Indices of sentences whose text came from OCR.

    Returns
    -------
    list[Claim]
    """
    ocr_set = ocr_sentence_indices or frozenset()
    claims: list[Claim] = []
    claim_counter = 0

    for i, sent in enumerate(sentences):
        if not _is_checkable(sent):
            continue

        markers = _extract_citation_markers(sent)

        # Context window
        ctx_before_sents = sentences[max(0, i - CONTEXT_SENTENCES) : i]
        ctx_after_sents = sentences[i + 1 : i + 1 + CONTEXT_SENTENCES]

        char_start, char_end = char_offsets[i]
        numbers = _NUMBER_RE.findall(sent)

        flags: list[str] = []
        if not markers:
            flags.append(Flags.NO_CITATION)
        if i in ocr_set:
            flags.append(Flags.OCR_TEXT)

        claim_id = f"{doc_id}_claim_{claim_counter:04d}"
        claim_counter += 1

        claims.append(
            Claim(
                claim_id=claim_id,
                doc_id=doc_id,
                text=sent,
                page=page_map[i],
                section=section_map[i],
                char_start=char_start,
                char_end=char_end,
                citation_markers=markers,
                reference_ids=_markers_to_ref_ids(markers, ref_index),
                claim_type=_classify_claim(sent),
                numbers_mentioned=numbers,
                context_before=" ".join(ctx_before_sents),
                context_after=" ".join(ctx_after_sents),
                flags=flags,
            )
        )

    return claims
