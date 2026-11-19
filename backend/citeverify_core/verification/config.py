"""
verification/config.py – All tuneable thresholds and weights for M3.

Values are sourced from env vars where noted; fall back to the defaults
specified in the Decisions Addendum.  Change defaults here, not in code.
"""

from __future__ import annotations

import os


# ---------------------------------------------------------------------------
# Confidence weights  (must sum to 1.0)
# ---------------------------------------------------------------------------

WEIGHT_RETRIEVAL: float = float(os.environ.get("CV_W_RETRIEVAL", "0.20"))
WEIGHT_LLM_CERTAINTY: float = float(os.environ.get("CV_W_LLM_CERTAINTY", "0.30"))
WEIGHT_TEXT_MATCH: float = float(os.environ.get("CV_W_TEXT_MATCH", "0.20"))
WEIGHT_FULL_TEXT: float = float(os.environ.get("CV_W_FULL_TEXT", "0.10"))
WEIGHT_NUMERIC_MATCH: float = float(os.environ.get("CV_W_NUMERIC_MATCH", "0.20"))

# ---------------------------------------------------------------------------
# Full-text component values by text_level / flag
# ---------------------------------------------------------------------------

FULL_TEXT_SCORE_FULL: float = 1.0
FULL_TEXT_SCORE_OCR: float = 0.7          # text_level="full_text" but "ocr_text" flag present
FULL_TEXT_SCORE_ABSTRACT_ONLY: float = 0.4
FULL_TEXT_SCORE_METADATA_ONLY: float = 0.2
FULL_TEXT_SCORE_NONE: float = 0.0

# ---------------------------------------------------------------------------
# Confidence caps and thresholds
# ---------------------------------------------------------------------------

# Verdict confidence below this threshold → needs_human_review = True
HUMAN_REVIEW_CONFIDENCE_THRESHOLD: float = float(
    os.environ.get("CV_HUMAN_REVIEW_THRESHOLD", "0.60")
)

# abstract_only sources: cap overall confidence at this value
ABSTRACT_ONLY_CONFIDENCE_CAP: float = float(
    os.environ.get("CV_ABSTRACT_ONLY_CAP", "0.50")
)

# ---------------------------------------------------------------------------
# Retrieval / search thresholds  (used by M2, referenced here for record)
# ---------------------------------------------------------------------------

# Cosine similarity below this → flag "low_retrieval_score"
LOW_RETRIEVAL_SCORE_THRESHOLD: float = float(
    os.environ.get("CV_LOW_RETRIEVAL_THRESHOLD", "0.35")
)

# Fuzzy match ratio for locate_quote (0–100)
QUOTE_FUZZY_THRESHOLD: float = float(os.environ.get("CV_QUOTE_FUZZY_THRESHOLD", "90"))

# ---------------------------------------------------------------------------
# Possibly-outdated rule
# ---------------------------------------------------------------------------

# Source older than this many years AND LLM says time-sensitive → possibly_outdated
POSSIBLY_OUTDATED_YEARS: int = int(os.environ.get("CV_POSSIBLY_OUTDATED_YEARS", "10"))

# ---------------------------------------------------------------------------
# flags that force needs_human_review = True (beyond the confidence threshold)
# ---------------------------------------------------------------------------

HUMAN_REVIEW_FORCE_FLAGS: frozenset[str] = frozenset(
    {
        "quote_not_verified",
        "number_not_found",
        "scope_mismatch",
        "possibly_retracted",
        "ocr_text",
        "abstract_only",
        "full_text_unavailable",
    }
)

# Verdicts that force needs_human_review = True
HUMAN_REVIEW_FORCE_VERDICTS: frozenset[str] = frozenset(
    {"needs_review", "contradictory", "possibly_outdated"}
)
