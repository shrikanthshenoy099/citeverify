"""
tests/m3/test_verdict.py – Unit tests for verification/verdict.py.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("LLM_PROVIDER", "mock")

from citeverify_core.verification.verdict import (
    build_prompts,
    maybe_override_possibly_outdated,
    parse_llm_response,
)
from citeverify_core.common.schemas import Claim, Reference, Source


def _make_source(year=2020, text_level="full_text") -> Source:
    return Source(
        reference_id="ref-x",
        matched=True,
        match_score=0.9,
        title="Test Paper",
        authors=["Author, A."],
        year=year,
        doi="10.1234/test",
        text_level=text_level,
        full_text_available=True,
        source_database="test",
        flags=[],
    )


def _make_reference(year=2020) -> Reference:
    return Reference(
        reference_id="ref-x",
        raw_text="Author (2020) Test Paper.",
        title="Test Paper",
        authors=["Author, A."],
        year=year,
        doi="10.1234/test",
        parse_confidence=0.9,
    )


def _make_claim() -> Claim:
    return Claim(
        claim_id="c-001",
        doc_id="d-001",
        text="Accuracy was 95%.",
        char_start=0,
        char_end=18,
        claim_type="numeric",
        numbers_mentioned=["95%"],
        context_before="",
        context_after="",
        flags=[],
    )


class TestBuildPrompts:
    def test_returns_two_strings(self):
        claim = _make_claim()
        ref = _make_reference()
        source = _make_source()
        system, user = build_prompts(claim, ref, source, passages=["Some passage text."])
        assert isinstance(system, str) and len(system) > 10
        assert isinstance(user, str) and len(user) > 10

    def test_claim_text_in_user_prompt(self):
        claim = _make_claim()
        ref = _make_reference()
        source = _make_source()
        _, user = build_prompts(claim, ref, source, passages=[])
        assert claim.text in user

    def test_no_passages_placeholder(self):
        claim = _make_claim()
        ref = _make_reference()
        source = _make_source()
        _, user = build_prompts(claim, ref, source, passages=[])
        assert "(No text retrieved)" in user

    def test_numbers_included(self):
        claim = _make_claim()
        ref = _make_reference()
        source = _make_source()
        _, user = build_prompts(claim, ref, source, passages=[])
        assert "95%" in user


class TestMaybeOverridePossiblyOutdated:
    def test_old_time_sensitive_becomes_possibly_outdated(self):
        result = maybe_override_possibly_outdated("supported", source_year=2000, time_sensitive=True)
        assert result == "possibly_outdated"

    def test_recent_source_no_override(self):
        result = maybe_override_possibly_outdated("supported", source_year=2023, time_sensitive=True)
        assert result == "supported"

    def test_not_time_sensitive_no_override(self):
        result = maybe_override_possibly_outdated("supported", source_year=2000, time_sensitive=False)
        assert result == "supported"

    def test_contradictory_never_overridden(self):
        result = maybe_override_possibly_outdated("contradictory", source_year=2000, time_sensitive=True)
        assert result == "contradictory"

    def test_none_year_no_override(self):
        result = maybe_override_possibly_outdated("supported", source_year=None, time_sensitive=True)
        assert result == "supported"


class TestParseLlmResponse:
    def test_parses_valid_response(self):
        data = {
            "verdict": "supported",
            "explanation": "Direct match.",
            "llm_certainty": 0.9,
            "supporting_quote": "accuracy was 95%",
            "time_sensitive": False,
            "numbers_match": True,
            "scope_mismatch": False,
        }
        v, exp, cert, quote, ts, nm, sm = parse_llm_response(data)
        assert v == "supported"
        assert cert == 0.9
        assert quote == "accuracy was 95%"
        assert ts is False
        assert nm is True
        assert sm is False

    def test_missing_supporting_quote_defaults_to_none(self):
        data = {
            "verdict": "unsupported",
            "explanation": "Not found.",
            "llm_certainty": 0.3,
            "time_sensitive": False,
            "numbers_match": False,
            "scope_mismatch": False,
        }
        _, _, _, quote, _, _, _ = parse_llm_response(data)
        assert quote is None
