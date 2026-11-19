"""
doc_intel/claim_extractor.py – sentence-level claim extraction.

Uses pysbd for sentence segmentation.  For each sentence decides:
  - Is it a checkable claim?  (heuristics, then LLM batch)
  - What claim type is it?    (LLM: numeric | factual | conclusion | methodological)
  - What citation markers does it carry?
  - Which reference IDs (by marker) does it link to?
  - What numbers does it mention?

LLM classification is batched: a single llm_client.complete_json call is made for
each batch of CLAIM_BATCH_SIZE candidate sentences (default 20), so a 100-sentence
document produces at most ceil(candidates/20) LLM calls, not one per sentence.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from citeverify_core.common.schemas import Claim, ClaimType, Flags
from citeverify_core.doc_intel.config import CLAIM_MIN_CHARS, CONTEXT_SENTENCES, CLAIM_BATCH_SIZE

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Citation marker patterns
# ---------------------------------------------------------------------------

# Numeric markers with optional en-dash (U+2013) or em-dash (U+2014) in ranges.
# Matches: [1], [1,2], [1, 3], [1-4], [1–4], [1—4], [1,3-5], (1), (1,2), etc.
_NUMERIC_MARKER_RE = re.compile(
    r"(?:"
    r"\[(?:\d+(?:[,\-\u2013\u2014]\s*\d+)*)\]"
    r"|"
    r"\((?:\d+(?:[,\-\u2013\u2014]\s*\d+)*)\)"
    r")"
)

# Author-year markers – parenthesised form:
#   (Smith, 2020), (Smith & Lee, 2020), (Smith et al., 2020), (Smith 2020a),
#   (Smith, 2020; Jones, 2019) – split on ";" to get individual markers.
# Pattern matches one entry within parens: Surname [et al.] [& Surname] year[a-z]
_AY_ENTRY_RE = re.compile(
    r"[A-Z][a-zA-Zéàüö'\-]+"          # first-author surname
    r"(?:\s+et\s+al\.?)?"              # optional et al.
    r"(?:,?\s*(?:&|and)\s+[A-Z][a-zA-Zéàüö'\-]+)?"  # optional second author
    r",?\s*\d{4}[a-z]?"               # year with optional letter suffix
)

# Full parenthesised block that may contain multiple author-year entries
_AY_PAREN_RE = re.compile(r"\((" + _AY_ENTRY_RE.pattern + r"(?:\s*;\s*" + _AY_ENTRY_RE.pattern + r")*)\)")

# Narrative form: Smith et al. (2020) or Smith (2020)
_NARRATIVE_AY_RE = re.compile(
    r"([A-Z][a-zA-Zéàüö'\-]+(?:\s+et\s+al\.?)?)"
    r"\s*\((\d{4}[a-z]?)\)"
)

# Numbers mentioned in a sentence (decimals, percentages, ranges)
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?(?:\s*%)?")


# ---------------------------------------------------------------------------
# Range expansion helper
# ---------------------------------------------------------------------------

def _expand_numeric_marker(marker: str) -> list[str]:
    """
    Expand a marker like [1-4] or [1,3-5] into individual markers [1],[3],[4],[5].
    Returns the original marker unchanged if it is a single number or not a range.
    """
    # Strip outer brackets / parens
    open_br = marker[0]
    close_br = marker[-1]
    inner = marker[1:-1]

    result: list[int] = []
    for part in re.split(r",\s*", inner):
        part = part.strip()
        range_m = re.match(r"^(\d+)\s*[-\u2013\u2014]\s*(\d+)$", part)
        if range_m:
            lo, hi = int(range_m.group(1)), int(range_m.group(2))
            result.extend(range(lo, hi + 1))
        else:
            try:
                result.append(int(part))
            except ValueError:
                pass

    if not result:
        return [marker]
    if len(result) == 1 and inner == str(result[0]):
        return [marker]  # already single, keep original form
    return [f"{open_br}{n}{close_br}" for n in result]


# ---------------------------------------------------------------------------
# Citation marker extraction
# ---------------------------------------------------------------------------

def _extract_citation_markers(text: str) -> list[str]:
    """
    Extract all citation markers from *text* and return them as a list of strings.

    - Numeric markers [1], [1,2], [1–4] are expanded into individual markers.
    - Author-year markers (Smith, 2020), (Smith et al., 2020; Jones, 2019),
      (Smith & Lee, 2020), (Smith 2020a) are extracted as full canonical strings.
    - Narrative form "Smith et al. (2020)" is captured as "(Smith et al., 2020)".
    - Duplicate markers are removed (preserve first occurrence).
    """
    markers: list[str] = []

    # --- Numeric ---
    for raw in _NUMERIC_MARKER_RE.findall(text):
        markers.extend(_expand_numeric_marker(raw))

    # --- Parenthesised author-year (possibly semicolon-separated) ---
    for m in _AY_PAREN_RE.finditer(text):
        inner = m.group(1)
        # Split on semicolons to get individual entries
        for entry in re.split(r"\s*;\s*", inner):
            entry = entry.strip()
            if _AY_ENTRY_RE.fullmatch(entry):
                markers.append(f"({entry})")

    # --- Narrative form: Smith et al. (2020) ---
    for m in _NARRATIVE_AY_RE.finditer(text):
        surname_part = m.group(1).strip()
        year = m.group(2)
        # Check the paren is NOT already captured as an AY paren marker
        canonical = f"({surname_part}, {year})"
        # Avoid re-adding if it matches something already there
        if canonical not in markers:
            markers.append(canonical)

    return list(dict.fromkeys(markers))  # deduplicate, preserve order


# ---------------------------------------------------------------------------
# ref_index lookup with reference_not_found flag support
# ---------------------------------------------------------------------------

def _markers_to_ref_ids(
    markers: list[str],
    ref_index: dict[str, str],
) -> tuple[list[str], list[str]]:
    """
    Map citation markers to reference IDs.

    Returns
    -------
    (reference_ids, unresolved_markers)
        reference_ids:       resolved ids (deduplicated)
        unresolved_markers:  markers that had no match in ref_index
    """
    ids: list[str] = []
    unresolved: list[str] = []
    for m in markers:
        rid = ref_index.get(m)
        if rid:
            ids.append(rid)
        else:
            unresolved.append(m)
    return list(dict.fromkeys(ids)), unresolved


# ---------------------------------------------------------------------------
# Heuristic claim-type classification (pre-LLM fast path)
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
    """Fast heuristic classification used as default / LLM fallback."""
    nums = _NUMBER_RE.findall(text)
    if len(nums) >= 1 and _NUMERIC_SIGNALS.search(text):
        return "numeric"
    if _CONCLUSION_SIGNALS.search(text):
        return "conclusion"
    if _METHODOLOGICAL_SIGNALS.search(text):
        return "methodological"
    return "factual"


# ---------------------------------------------------------------------------
# LLM batch classification
# ---------------------------------------------------------------------------

_CLASSIFY_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "is_verifiable_claim": {"type": "boolean"},
                    "claim_type": {
                        "type": "string",
                        "enum": ["numeric", "factual", "conclusion", "methodological"],
                    },
                    "numbers_mentioned": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["index", "is_verifiable_claim", "claim_type", "numbers_mentioned"],
            },
        }
    },
    "required": ["results"],
}

_CLASSIFY_SYSTEM = (
    "You are a scientific claim classifier. "
    "Given a numbered list of sentences, for each one determine: "
    "(1) is_verifiable_claim: true only if the sentence makes a checkable factual, numeric, "
    "methodological or concluding statement about the world. "
    "Exclude opinions, definitions, transitions, questions, and statements about "
    "this document's own work (e.g. 'In this paper we propose'). "
    "(2) claim_type: numeric|factual|conclusion|methodological. "
    "(3) numbers_mentioned: list of numeric values/percentages/ranges in the sentence. "
    "Return JSON with key 'results' as an array of objects with keys: "
    "index, is_verifiable_claim, claim_type, numbers_mentioned."
)


def _llm_classify_batch(
    sentences: list[str],
    base_indices: list[int],
) -> dict[int, dict]:
    """
    Call the LLM to classify a batch of candidate sentences.

    Returns a dict mapping original sentence index -> classification dict
    with keys: is_verifiable_claim, claim_type, numbers_mentioned.
    Falls back to heuristics for any sentence the LLM doesn't cover.
    """
    from citeverify_core.common.llm_client import get_llm_client

    numbered = "\n".join(f"{i}. {s.strip()}" for i, s in zip(base_indices, sentences))
    user_prompt = f"Classify these sentences:\n{numbered}"

    try:
        result = get_llm_client().complete_json(
            system=_CLASSIFY_SYSTEM,
            user=user_prompt,
            schema=_CLASSIFY_SCHEMA,
            temperature=0.0,
        )
        return {item["index"]: item for item in result.get("results", [])}
    except Exception as exc:
        logger.warning("LLM batch classification failed, using heuristics: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# Checkable sentence filter
# ---------------------------------------------------------------------------

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
        LLM classification is called in batches of CLAIM_BATCH_SIZE.
        For a 100-sentence document with 60 candidates this means ceil(60/20) = 3 LLM calls.
    """
    ocr_set = ocr_sentence_indices or frozenset()

    # ------------------------------------------------------------------
    # Pass 1: collect heuristic candidates and their context
    # ------------------------------------------------------------------
    candidates: list[tuple[int, str]] = []  # (original_index, sentence)
    for i, sent in enumerate(sentences):
        if _is_checkable(sent):
            candidates.append((i, sent))

    # ------------------------------------------------------------------
    # Pass 2: LLM batch classification
    # ------------------------------------------------------------------
    llm_results: dict[int, dict] = {}
    for batch_start in range(0, len(candidates), CLAIM_BATCH_SIZE):
        batch = candidates[batch_start: batch_start + CLAIM_BATCH_SIZE]
        orig_indices = [idx for idx, _ in batch]
        texts = [s for _, s in batch]
        batch_result = _llm_classify_batch(texts, orig_indices)
        llm_results.update(batch_result)

    logger.debug(
        "[M1] doc=%s candidates=%d llm_batches=%d",
        doc_id,
        len(candidates),
        (len(candidates) + CLAIM_BATCH_SIZE - 1) // max(CLAIM_BATCH_SIZE, 1),
    )

    # ------------------------------------------------------------------
    # Pass 3: build Claim objects
    # ------------------------------------------------------------------
    claims: list[Claim] = []
    claim_counter = 0
    seen_texts: set[str] = set()

    for orig_idx, sent in candidates:
        llm_info = llm_results.get(orig_idx, {})

        # LLM may mark sentence as non-verifiable – skip it
        if llm_info.get("is_verifiable_claim") is False:
            continue

        # Near-duplicate removal (strip whitespace for comparison)
        normalized = sent.strip()
        if normalized in seen_texts:
            continue
        seen_texts.add(normalized)

        markers = _extract_citation_markers(sent)
        ref_ids, unresolved = _markers_to_ref_ids(markers, ref_index)

        # Context window
        ctx_before_sents = sentences[max(0, orig_idx - CONTEXT_SENTENCES): orig_idx]
        ctx_after_sents = sentences[orig_idx + 1: orig_idx + 1 + CONTEXT_SENTENCES]

        char_start, char_end = char_offsets[orig_idx]

        # LLM-enriched numbers, falling back to regex
        if llm_info.get("numbers_mentioned"):
            numbers = llm_info["numbers_mentioned"]
        else:
            numbers = _NUMBER_RE.findall(sent)

        # LLM-enriched claim type, falling back to heuristic
        claim_type: ClaimType = llm_info.get("claim_type") or _classify_claim(sent)  # type: ignore[assignment]

        flags: list[str] = []
        if not markers:
            flags.append(Flags.NO_CITATION)
        if unresolved:
            flags.append(Flags.REFERENCE_NOT_FOUND)
        if orig_idx in ocr_set:
            flags.append(Flags.OCR_TEXT)

        claim_id = f"{doc_id}_claim_{claim_counter:04d}"
        claim_counter += 1

        claims.append(
            Claim(
                claim_id=claim_id,
                doc_id=doc_id,
                text=sent,
                page=page_map[orig_idx],
                section=section_map[orig_idx],
                char_start=char_start,
                char_end=char_end,
                citation_markers=markers,
                reference_ids=ref_ids,
                claim_type=claim_type,
                numbers_mentioned=numbers,
                context_before=" ".join(ctx_before_sents),
                context_after=" ".join(ctx_after_sents),
                flags=flags,
            )
        )

    return claims
