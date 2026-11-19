"""
verification/confidence.py – Confidence score computation for M3.

Computes the weighted overall confidence and the per-component breakdown
using the thresholds defined in verification/config.py.
"""

from __future__ import annotations

import logging

from citeverify_core.common.schemas import (
    ConfidenceBreakdown,
    Source,
)
from citeverify_core.verification import config

logger = logging.getLogger(__name__)


def compute_full_text_component(source: Source) -> float:
    """
    Return the full-text sub-score based on text availability and flags.

    Rules (from Decisions Addendum):
      - "ocr_text" flag present → 0.7 (regardless of text_level)
      - text_level="full_text"  → 1.0
      - text_level="abstract_only" → 0.4
      - text_level="metadata_only" → 0.2
      - text_level="none"       → 0.0
    """
    if "ocr_text" in source.flags:
        return config.FULL_TEXT_SCORE_OCR

    mapping = {
        "full_text": config.FULL_TEXT_SCORE_FULL,
        "abstract_only": config.FULL_TEXT_SCORE_ABSTRACT_ONLY,
        "metadata_only": config.FULL_TEXT_SCORE_METADATA_ONLY,
        "none": config.FULL_TEXT_SCORE_NONE,
    }
    score = mapping.get(source.text_level, config.FULL_TEXT_SCORE_NONE)
    return score


def compute_confidence(
    *,
    retrieval_score: float,
    llm_certainty: float,
    text_match_score: float,
    source: Source,
    numbers_match: bool,
    flags: list[str],
    verdict: str,
) -> tuple[float, ConfidenceBreakdown]:
    """
    Compute overall confidence and its breakdown.

    Parameters
    ----------
    retrieval_score:  Top cosine similarity score from passage search (0–1).
    llm_certainty:    Certainty value returned by the LLM (0–1).
    text_match_score: Fuzzy/exact text-match quality (0–1).
    source:           The Source object for the current (claim, reference) pair.
    numbers_match:    Whether numeric figures in the claim match the source.
    flags:            Flags collected so far (mutated by caller, not here).
    verdict:          The verdict string (checked against caps/rules).

    Returns
    -------
    (overall_confidence, ConfidenceBreakdown)
    overall_confidence is already capped by abstract_only rule if applicable.
    """
    full_text_component = compute_full_text_component(source)
    numeric_component = 1.0 if numbers_match else 0.0

    breakdown = ConfidenceBreakdown(
        retrieval=_clamp(retrieval_score),
        llm_certainty=_clamp(llm_certainty),
        text_match=_clamp(text_match_score),
        full_text=full_text_component,
        numeric_match=numeric_component,
    )

    overall = (
        config.WEIGHT_RETRIEVAL * breakdown.retrieval
        + config.WEIGHT_LLM_CERTAINTY * breakdown.llm_certainty
        + config.WEIGHT_TEXT_MATCH * breakdown.text_match
        + config.WEIGHT_FULL_TEXT * breakdown.full_text
        + config.WEIGHT_NUMERIC_MATCH * breakdown.numeric_match
    )
    overall = _clamp(overall)

    # Cap confidence for abstract-only sources
    if source.text_level == "abstract_only" or "abstract_only" in flags:
        if overall > config.ABSTRACT_ONLY_CONFIDENCE_CAP:
            logger.debug(
                "Confidence capped at %.2f (abstract_only); was %.2f.",
                config.ABSTRACT_ONLY_CONFIDENCE_CAP,
                overall,
            )
            overall = config.ABSTRACT_ONLY_CONFIDENCE_CAP

    return overall, breakdown


def requires_human_review(
    confidence: float,
    verdict: str,
    flags: list[str],
) -> bool:
    """
    Return True if the result must be escalated to a human reviewer.

    Triggers:
      - confidence < HUMAN_REVIEW_CONFIDENCE_THRESHOLD
      - verdict in HUMAN_REVIEW_FORCE_VERDICTS
      - any flag in HUMAN_REVIEW_FORCE_FLAGS
    """
    if confidence < config.HUMAN_REVIEW_CONFIDENCE_THRESHOLD:
        return True
    if verdict in config.HUMAN_REVIEW_FORCE_VERDICTS:
        return True
    if config.HUMAN_REVIEW_FORCE_FLAGS.intersection(flags):
        return True
    return False


def _clamp(value: float) -> float:
    """Clamp a float to [0.0, 1.0]."""
    return max(0.0, min(1.0, value))
