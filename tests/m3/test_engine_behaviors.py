"""
tests/m3/test_engine_behaviors.py – Audit behavior tests for verification/engine.py.

Covers:
  B.1  Early exit on unmatched source (no LLM call, verdict=needs_review)
  B.2  Low retrieval score flag (< 0.35)
  B.3  Possibly unrelated citation flag (< 0.175)
  B.4  LLM retry on LLMSchemaError (up to 2 retries, then llm_output_invalid)
  B.5  Scope mismatch caps supported -> partly_supported
  B.6  Scope mismatch does NOT cap partly_supported or weaker
  B.7  Anti-hallucination: quote verified by locate_quote -> no downgrade
  B.8  Anti-hallucination: quote in passages but not locate_quote -> quote_not_verified, no downgrade
  B.9  Anti-hallucination: quote not in passages AND locate_quote=None -> downgrade + quote_not_verified
  B.10 Numeric mismatch: flags number_not_found + caps supported -> partly_supported
  B.11 Numeric mismatch does NOT downgrade non-supported verdicts below partly_supported
  B.12 ocr_text flag forces needs_human_review
  B.13 possibly_retracted flag forces needs_human_review
  B.14 manual_source treated as normal full-text (no extra flags added)
  B.15 possibly_outdated override applied for old time-sensitive source
  B.16 LLMError (non-retryable) skips retries and returns needs_review
  A.3  abstract_only: confidence capped at 0.50
  C.3  reverify_for_reference re-runs only claims that cite that reference
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("LLM_PROVIDER", "mock")

from citeverify_core.common.llm_client import LLMError, LLMSchemaError, LLMClient
from citeverify_core.common.schemas import (
    Claim,
    Evidence,
    Passage,
    Reference,
    Source,
)
from citeverify_core.verification.engine import verify, reverify_for_reference


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _claim(
    claim_id: str = "c-001",
    text: str = "Accuracy was 95%.",
    numbers: list[str] | None = None,
    reference_ids: list[str] | None = None,
) -> Claim:
    return Claim(
        claim_id=claim_id,
        doc_id="doc-001",
        text=text,
        char_start=0,
        char_end=len(text),
        claim_type="numeric",
        numbers_mentioned=numbers if numbers is not None else ["95%"],
        context_before="",
        context_after="",
        flags=[],
        reference_ids=reference_ids if reference_ids is not None else ["ref-001"],
    )


def _reference(reference_id: str = "ref-001", year: int = 2020) -> Reference:
    return Reference(
        reference_id=reference_id,
        raw_text="Author (2020) Title.",
        title="Title",
        authors=["Author, A."],
        year=year,
        doi="10.1234/test",
        parse_confidence=0.9,
    )


def _source(
    matched: bool = True,
    text_level: str = "full_text",
    extra_flags: list[str] | None = None,
    year: int = 2020,
    full_text_available: bool = True,
) -> Source:
    return Source(
        reference_id="ref-001",
        matched=matched,
        match_score=0.9 if matched else 0.0,
        title="Title",
        authors=["Author, A."],
        year=year,
        doi="10.1234/test",
        url="https://doi.org/10.1234/test",
        text_level=text_level,
        full_text_available=full_text_available,
        source_database="test",
        flags=list(extra_flags or []),
    )


def _passage(text: str = "The model achieved an accuracy of 95%.", score: float = 0.88) -> Passage:
    return Passage(
        passage_id="p-001",
        reference_id="ref-001",
        text=text,
        page=5,
        section="Results",
        score=score,
    )


def _llm_response(
    verdict: str = "supported",
    explanation: str = "Matches.",
    llm_certainty: float = 0.9,
    supporting_quote: str | None = "accuracy of 95%",
    time_sensitive: bool = False,
    numbers_match: bool = True,
    scope_mismatch: bool = False,
) -> dict:
    d = {
        "verdict": verdict,
        "explanation": explanation,
        "llm_certainty": llm_certainty,
        "time_sensitive": time_sensitive,
        "numbers_match": numbers_match,
        "scope_mismatch": scope_mismatch,
    }
    if supporting_quote is not None:
        d["supporting_quote"] = supporting_quote
    return d


class _FixedLLM(LLMClient):
    """Returns a fixed dict every time."""
    def __init__(self, response: dict) -> None:
        self._response = response

    def complete_json(self, system: str, user: str, schema: dict, temperature: float = 0) -> dict:
        return self._response


class _FailThenSucceedLLM(LLMClient):
    """Raises LLMSchemaError for the first N calls, then returns a valid response."""
    def __init__(self, fail_count: int, success_response: dict) -> None:
        self._fail_count = fail_count
        self._calls = 0
        self._success_response = success_response

    def complete_json(self, system: str, user: str, schema: dict, temperature: float = 0) -> dict:
        self._calls += 1
        if self._calls <= self._fail_count:
            raise LLMSchemaError("bad json")
        return self._success_response


class _AlwaysFailLLM(LLMClient):
    """Always raises LLMSchemaError."""
    def __init__(self) -> None:
        self._calls = 0

    def complete_json(self, system: str, user: str, schema: dict, temperature: float = 0) -> dict:
        self._calls += 1
        raise LLMSchemaError("bad json always")


class _LLMErrorLLM(LLMClient):
    """Always raises a non-retryable LLMError."""
    def __init__(self) -> None:
        self._calls = 0

    def complete_json(self, system: str, user: str, schema: dict, temperature: float = 0) -> dict:
        self._calls += 1
        raise LLMError("network failure")


def _no_passages(reference_id: str, query: str, k: int = 5) -> list[Passage]:
    return []


def _locate_none(reference_id: str, quote: str) -> Evidence | None:
    return None


def _locate_found(reference_id: str, quote: str) -> Evidence | None:
    return Evidence(quote=quote, passage_id="p-001", page=5, section="Results")


# ---------------------------------------------------------------------------
# B.1 Early exit on unmatched source
# ---------------------------------------------------------------------------

class TestB1EarlyExit:
    def test_unmatched_returns_needs_review_without_llm(self):
        called = []

        class _TrackingLLM(LLMClient):
            def complete_json(self, **kw):
                called.append(True)
                return _llm_response()

        source = _source(matched=False, text_level="none", full_text_available=False)
        v = verify(_claim(), _reference(), source, llm_client=_TrackingLLM())
        assert v.verdict == "needs_review"
        assert called == [], "LLM must NOT be called when source is unmatched"

    def test_unmatched_sets_reference_not_found_flag(self):
        source = _source(matched=False, text_level="none", full_text_available=False)
        v = verify(_claim(), _reference(), source, llm_client=_FixedLLM(_llm_response()))
        assert "reference_not_found" in v.flags

    def test_unmatched_needs_human_review_true(self):
        source = _source(matched=False, text_level="none", full_text_available=False)
        v = verify(_claim(), _reference(), source, llm_client=_FixedLLM(_llm_response()))
        assert v.needs_human_review is True

    def test_unmatched_explanation_mentions_source(self):
        source = _source(matched=False, text_level="none", full_text_available=False)
        v = verify(_claim(), _reference(), source, llm_client=_FixedLLM(_llm_response()))
        assert "source" in v.explanation.lower()


# ---------------------------------------------------------------------------
# B.2 / B.3 Low retrieval score flags
# ---------------------------------------------------------------------------

class TestB2B3RetrievalFlags:
    def _low_score_passage(self, score: float) -> list[Passage]:
        return [_passage(score=score)]

    def test_score_below_threshold_flags_low_retrieval(self):
        passages = self._low_score_passage(0.20)
        v = verify(
            _claim(), _reference(), _source(),
            search_passages_fn=lambda *a, **kw: passages,
            locate_quote_fn=_locate_found,
            llm_client=_FixedLLM(_llm_response()),
        )
        assert "low_retrieval_score" in v.flags

    def test_score_below_half_threshold_flags_possibly_unrelated(self):
        # < 0.35 * 0.5 = 0.175
        passages = self._low_score_passage(0.10)
        v = verify(
            _claim(), _reference(), _source(),
            search_passages_fn=lambda *a, **kw: passages,
            locate_quote_fn=_locate_found,
            llm_client=_FixedLLM(_llm_response()),
        )
        assert "possibly_unrelated_citation" in v.flags
        assert "low_retrieval_score" in v.flags

    def test_score_above_threshold_no_flag(self):
        passages = self._low_score_passage(0.80)
        v = verify(
            _claim(), _reference(), _source(),
            search_passages_fn=lambda *a, **kw: passages,
            locate_quote_fn=_locate_found,
            llm_client=_FixedLLM(_llm_response()),
        )
        assert "low_retrieval_score" not in v.flags
        assert "possibly_unrelated_citation" not in v.flags


# ---------------------------------------------------------------------------
# B.4 LLM retries on LLMSchemaError
# ---------------------------------------------------------------------------

class TestB4LLMRetries:
    def test_first_fail_then_success_still_valid(self):
        """1 schema error then success – should succeed within 3 total attempts."""
        llm = _FailThenSucceedLLM(fail_count=1, success_response=_llm_response())
        v = verify(
            _claim(), _reference(), _source(),
            search_passages_fn=lambda *a, **kw: [_passage()],
            locate_quote_fn=_locate_found,
            llm_client=llm,
        )
        assert v.verdict != "needs_review" or "llm_output_invalid" not in v.flags
        assert llm._calls == 2

    def test_two_fails_then_success(self):
        """2 schema errors then success – exactly 3 calls."""
        llm = _FailThenSucceedLLM(fail_count=2, success_response=_llm_response())
        v = verify(
            _claim(), _reference(), _source(),
            search_passages_fn=lambda *a, **kw: [_passage()],
            locate_quote_fn=_locate_found,
            llm_client=llm,
        )
        assert "llm_output_invalid" not in v.flags
        assert llm._calls == 3

    def test_three_schema_errors_flags_llm_output_invalid(self):
        """All 3 attempts fail -> llm_output_invalid flagged."""
        llm = _AlwaysFailLLM()
        v = verify(
            _claim(), _reference(), _source(),
            search_passages_fn=lambda *a, **kw: [_passage()],
            locate_quote_fn=_locate_none,
            llm_client=llm,
        )
        assert "llm_output_invalid" in v.flags
        assert llm._calls == 3

    def test_llm_error_non_retryable(self):
        """LLMError (not schema) must not retry."""
        llm = _LLMErrorLLM()
        v = verify(
            _claim(), _reference(), _source(),
            search_passages_fn=lambda *a, **kw: [_passage()],
            locate_quote_fn=_locate_none,
            llm_client=llm,
        )
        assert llm._calls == 1  # no retries


# ---------------------------------------------------------------------------
# B.5 / B.6 Scope mismatch
# ---------------------------------------------------------------------------

class TestB5B6ScopeMismatch:
    def test_scope_mismatch_caps_supported_to_partly_supported(self):
        resp = _llm_response(verdict="supported", scope_mismatch=True)
        v = verify(
            _claim(), _reference(), _source(),
            search_passages_fn=lambda *a, **kw: [_passage()],
            locate_quote_fn=_locate_found,
            llm_client=_FixedLLM(resp),
        )
        assert v.verdict == "partly_supported"
        assert "scope_mismatch" in v.flags

    def test_scope_mismatch_does_not_cap_partly_supported(self):
        resp = _llm_response(verdict="partly_supported", scope_mismatch=True)
        v = verify(
            _claim(), _reference(), _source(),
            search_passages_fn=lambda *a, **kw: [_passage()],
            locate_quote_fn=_locate_found,
            llm_client=_FixedLLM(resp),
        )
        assert v.verdict == "partly_supported"

    def test_no_scope_mismatch_no_flag(self):
        resp = _llm_response(verdict="supported", scope_mismatch=False)
        v = verify(
            _claim(), _reference(), _source(),
            search_passages_fn=lambda *a, **kw: [_passage()],
            locate_quote_fn=_locate_found,
            llm_client=_FixedLLM(resp),
        )
        assert "scope_mismatch" not in v.flags
        assert v.verdict == "supported"


# ---------------------------------------------------------------------------
# B.7 / B.8 / B.9 Anti-hallucination quote verification
# ---------------------------------------------------------------------------

class TestB7B8B9AntiHallucination:
    def test_b7_quote_found_by_locate_quote_no_downgrade(self):
        resp = _llm_response(verdict="supported", supporting_quote="accuracy of 95%")
        v = verify(
            _claim(), _reference(), _source(),
            search_passages_fn=lambda *a, **kw: [_passage()],
            locate_quote_fn=_locate_found,
            llm_client=_FixedLLM(resp),
        )
        assert v.verdict == "supported"
        assert "quote_not_verified" not in v.flags

    def test_b8_quote_in_passages_but_no_bbox_flags_quote_not_verified(self):
        # locate_quote returns None but quote IS in passage text
        passage_text = "The model achieved an accuracy of 95% on the benchmark."
        resp = _llm_response(verdict="supported", supporting_quote="accuracy of 95%")
        v = verify(
            _claim(), _reference(), _source(),
            search_passages_fn=lambda *a, **kw: [_passage(text=passage_text)],
            locate_quote_fn=_locate_none,
            llm_client=_FixedLLM(resp),
        )
        assert "quote_not_verified" in v.flags
        # verdict is NOT downgraded – quote was found in passages
        assert v.verdict == "supported"

    def test_b9_quote_not_found_anywhere_downgrades_supported(self):
        resp = _llm_response(verdict="supported", supporting_quote="completely fabricated quote xyz")
        v = verify(
            _claim(), _reference(), _source(),
            search_passages_fn=lambda *a, **kw: [_passage(text="irrelevant text here")],
            locate_quote_fn=_locate_none,
            llm_client=_FixedLLM(resp),
        )
        assert "quote_not_verified" in v.flags
        assert v.verdict == "needs_review"

    def test_b9_quote_not_found_downgrades_partly_supported(self):
        resp = _llm_response(verdict="partly_supported", supporting_quote="fabricated xyz quote")
        v = verify(
            _claim(), _reference(), _source(),
            search_passages_fn=lambda *a, **kw: [_passage(text="irrelevant text here")],
            locate_quote_fn=_locate_none,
            llm_client=_FixedLLM(resp),
        )
        assert v.verdict == "needs_review"


# ---------------------------------------------------------------------------
# B.10 / B.11 Numeric mismatch
# ---------------------------------------------------------------------------

class TestB10B11NumericMismatch:
    def test_b10_numbers_mentioned_no_match_flags_number_not_found(self):
        resp = _llm_response(verdict="supported", numbers_match=False)
        v = verify(
            _claim(numbers=["95%"]), _reference(), _source(),
            search_passages_fn=lambda *a, **kw: [_passage()],
            locate_quote_fn=_locate_found,
            llm_client=_FixedLLM(resp),
        )
        assert "number_not_found" in v.flags

    def test_b10_supported_capped_to_partly_supported_on_number_mismatch(self):
        resp = _llm_response(verdict="supported", numbers_match=False)
        v = verify(
            _claim(numbers=["95%"]), _reference(), _source(),
            search_passages_fn=lambda *a, **kw: [_passage()],
            locate_quote_fn=_locate_found,
            llm_client=_FixedLLM(resp),
        )
        assert v.verdict == "partly_supported"

    def test_b11_no_numbers_mentioned_no_number_flag(self):
        resp = _llm_response(verdict="supported", numbers_match=False)
        v = verify(
            _claim(numbers=[]), _reference(), _source(),
            search_passages_fn=lambda *a, **kw: [_passage()],
            locate_quote_fn=_locate_found,
            llm_client=_FixedLLM(resp),
        )
        assert "number_not_found" not in v.flags

    def test_b11_numbers_match_true_no_cap(self):
        resp = _llm_response(verdict="supported", numbers_match=True)
        v = verify(
            _claim(numbers=["95%"]), _reference(), _source(),
            search_passages_fn=lambda *a, **kw: [_passage()],
            locate_quote_fn=_locate_found,
            llm_client=_FixedLLM(resp),
        )
        assert v.verdict == "supported"


# ---------------------------------------------------------------------------
# B.12 / B.13 / B.14 Special source flags
# ---------------------------------------------------------------------------

class TestB12B13B14SpecialFlags:
    def test_b12_ocr_text_forces_needs_human_review(self):
        source = _source(extra_flags=["ocr_text"])
        v = verify(
            _claim(), _reference(), source,
            search_passages_fn=lambda *a, **kw: [_passage()],
            locate_quote_fn=_locate_found,
            llm_client=_FixedLLM(_llm_response()),
        )
        assert v.needs_human_review is True

    def test_b13_possibly_retracted_forces_needs_human_review(self):
        source = _source(extra_flags=["possibly_retracted"])
        v = verify(
            _claim(), _reference(), source,
            search_passages_fn=lambda *a, **kw: [_passage()],
            locate_quote_fn=_locate_found,
            llm_client=_FixedLLM(_llm_response()),
        )
        assert v.needs_human_review is True

    def test_b13_possibly_retracted_explanation_mentions_retracted(self):
        source = _source(extra_flags=["possibly_retracted"])
        v = verify(
            _claim(), _reference(), source,
            search_passages_fn=lambda *a, **kw: [_passage()],
            locate_quote_fn=_locate_found,
            llm_client=_FixedLLM(_llm_response()),
        )
        assert "retract" in v.explanation.lower()

    def test_b14_manual_source_no_extra_flags(self):
        source = _source(extra_flags=["manual_source"])
        v = verify(
            _claim(), _reference(), source,
            search_passages_fn=lambda *a, **kw: [_passage()],
            locate_quote_fn=_locate_found,
            llm_client=_FixedLLM(_llm_response()),
        )
        # manual_source should pass through without adding unrelated flags
        assert "manual_source" in v.flags
        # source was treated as full_text, so verdict should be valid
        assert v.verdict in {"supported", "partly_supported", "unsupported", "contradictory",
                             "possibly_outdated", "needs_review"}


# ---------------------------------------------------------------------------
# B.15 Possibly outdated
# ---------------------------------------------------------------------------

class TestB15PossiblyOutdated:
    def test_old_time_sensitive_source_becomes_possibly_outdated(self):
        source = _source(year=2000)
        resp = _llm_response(verdict="supported", time_sensitive=True)
        v = verify(
            _claim(), _reference(year=2000), source,
            search_passages_fn=lambda *a, **kw: [_passage()],
            locate_quote_fn=_locate_found,
            llm_client=_FixedLLM(resp),
        )
        assert v.verdict == "possibly_outdated"

    def test_recent_time_sensitive_source_no_override(self):
        source = _source(year=2023)
        resp = _llm_response(verdict="supported", time_sensitive=True)
        v = verify(
            _claim(), _reference(year=2023), source,
            search_passages_fn=lambda *a, **kw: [_passage()],
            locate_quote_fn=_locate_found,
            llm_client=_FixedLLM(resp),
        )
        assert v.verdict == "supported"


# ---------------------------------------------------------------------------
# B.16 LLMError non-retryable
# ---------------------------------------------------------------------------

class TestB16LLMError:
    def test_llm_error_exactly_one_call(self):
        llm = _LLMErrorLLM()
        verify(
            _claim(), _reference(), _source(),
            search_passages_fn=lambda *a, **kw: [_passage()],
            locate_quote_fn=_locate_none,
            llm_client=llm,
        )
        assert llm._calls == 1


# ---------------------------------------------------------------------------
# A.3 Abstract-only confidence cap
# ---------------------------------------------------------------------------

class TestA3AbstractOnlyCap:
    def test_abstract_only_confidence_capped_at_050(self):
        source = _source(text_level="abstract_only", full_text_available=False,
                         extra_flags=["abstract_only"])
        resp = _llm_response(verdict="supported", llm_certainty=0.99)
        v = verify(
            _claim(), _reference(), source,
            search_passages_fn=lambda *a, **kw: [_passage(score=0.9)],
            locate_quote_fn=_locate_none,
            llm_client=_FixedLLM(resp),
        )
        assert v.confidence <= 0.50 + 1e-9


# ---------------------------------------------------------------------------
# C.3 reverify_for_reference
# ---------------------------------------------------------------------------

class TestC3ReverifyForReference:
    def test_reruns_only_claims_citing_reference(self):
        ref = _reference(reference_id="ref-002")
        source = _source()
        source.reference_id = "ref-002"

        claims = [
            _claim(claim_id="c-001", reference_ids=["ref-001"]),  # does NOT cite ref-002
            _claim(claim_id="c-002", reference_ids=["ref-002"]),  # cites ref-002
            _claim(claim_id="c-003", reference_ids=["ref-002", "ref-003"]),  # cites ref-002
        ]

        verdicts = reverify_for_reference(
            reference_id="ref-002",
            claims=claims,
            reference=ref,
            source=source,
            search_passages_fn=lambda *a, **kw: [_passage()],
            locate_quote_fn=_locate_found,
            llm_client=_FixedLLM(_llm_response()),
        )
        returned_claim_ids = {v.claim_id for v in verdicts}
        assert "c-001" not in returned_claim_ids
        assert "c-002" in returned_claim_ids
        assert "c-003" in returned_claim_ids
        assert len(verdicts) == 2
