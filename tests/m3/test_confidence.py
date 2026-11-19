"""
tests/m3/test_confidence.py – Unit tests for verification/confidence.py.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("LLM_PROVIDER", "mock")

from citeverify_core.common.schemas import Source
from citeverify_core.verification.confidence import (
    compute_confidence,
    compute_full_text_component,
    requires_human_review,
)
from citeverify_core.verification import config


def _make_source(text_level="full_text", flags=None) -> Source:
    return Source(
        reference_id="ref-x",
        matched=True,
        match_score=0.9,
        title="Test",
        text_level=text_level,
        full_text_available=text_level == "full_text",
        source_database="test",
        flags=flags or [],
    )


class TestFullTextComponent:
    def test_full_text_no_ocr(self):
        s = _make_source("full_text")
        assert compute_full_text_component(s) == config.FULL_TEXT_SCORE_FULL

    def test_full_text_with_ocr_flag(self):
        s = _make_source("full_text", flags=["ocr_text"])
        assert compute_full_text_component(s) == config.FULL_TEXT_SCORE_OCR

    def test_abstract_only(self):
        s = _make_source("abstract_only")
        assert compute_full_text_component(s) == config.FULL_TEXT_SCORE_ABSTRACT_ONLY

    def test_metadata_only(self):
        s = _make_source("metadata_only")
        assert compute_full_text_component(s) == config.FULL_TEXT_SCORE_METADATA_ONLY

    def test_none(self):
        s = _make_source("none")
        assert compute_full_text_component(s) == config.FULL_TEXT_SCORE_NONE


class TestComputeConfidence:
    def test_high_confidence_scenario(self):
        s = _make_source("full_text")
        overall, breakdown = compute_confidence(
            retrieval_score=0.9,
            llm_certainty=0.9,
            text_match_score=0.9,
            source=s,
            numbers_match=True,
            flags=[],
            verdict="supported",
        )
        # weights: 0.2*0.9 + 0.3*0.9 + 0.2*0.9 + 0.1*1.0 + 0.2*1.0 = 0.63
        assert overall > 0.6

    def test_abstract_only_cap(self):
        s = _make_source("abstract_only", flags=["abstract_only"])
        overall, _ = compute_confidence(
            retrieval_score=1.0,
            llm_certainty=1.0,
            text_match_score=1.0,
            source=s,
            numbers_match=True,
            flags=["abstract_only"],
            verdict="supported",
        )
        assert overall <= config.ABSTRACT_ONLY_CONFIDENCE_CAP

    def test_confidence_clamped_at_zero(self):
        s = _make_source("none")
        overall, _ = compute_confidence(
            retrieval_score=0.0,
            llm_certainty=0.0,
            text_match_score=0.0,
            source=s,
            numbers_match=False,
            flags=[],
            verdict="unsupported",
        )
        assert overall >= 0.0

    def test_breakdown_fields_present(self):
        s = _make_source("full_text")
        _, breakdown = compute_confidence(
            retrieval_score=0.5,
            llm_certainty=0.5,
            text_match_score=0.5,
            source=s,
            numbers_match=True,
            flags=[],
            verdict="supported",
        )
        for field in ("retrieval", "llm_certainty", "text_match", "full_text", "numeric_match"):
            val = getattr(breakdown, field)
            assert 0.0 <= val <= 1.0, f"{field} out of range: {val}"


class TestRequiresHumanReview:
    def test_low_confidence_triggers_review(self):
        assert requires_human_review(0.4, "supported", []) is True

    def test_needs_review_verdict_triggers(self):
        assert requires_human_review(0.9, "needs_review", []) is True

    def test_contradictory_verdict_triggers(self):
        assert requires_human_review(0.9, "contradictory", []) is True

    def test_possibly_outdated_triggers(self):
        assert requires_human_review(0.9, "possibly_outdated", []) is True

    def test_ocr_text_flag_triggers(self):
        assert requires_human_review(0.9, "supported", ["ocr_text"]) is True

    def test_possibly_retracted_flag_triggers(self):
        assert requires_human_review(0.9, "supported", ["possibly_retracted"]) is True

    def test_no_trigger_scenario(self):
        assert requires_human_review(0.8, "supported", []) is False
