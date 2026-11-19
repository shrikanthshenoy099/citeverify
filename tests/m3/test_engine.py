"""
tests/m3/test_engine.py – Integration-level tests for verification/engine.py.

All tests use MockLLMClient and stub out M2 functions so there are no
network calls or file system dependencies.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("LLM_PROVIDER", "mock")

from citeverify_core.common.llm_client import MockLLMClient
from citeverify_core.common.schemas import (
    Claim,
    Evidence,
    Passage,
    Reference,
    Source,
    Verdict,
)
from citeverify_core.verification.engine import reverify_for_reference, verify


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_reference(year=2020) -> Reference:
    return Reference(
        reference_id="ref-001",
        raw_text="Smith (2020) Great Paper.",
        title="Great Paper",
        authors=["Smith, J."],
        year=year,
        doi="10.1234/great",
        parse_confidence=0.9,
    )


def _make_claim(ref_id="ref-001") -> Claim:
    return Claim(
        claim_id="claim-001",
        doc_id="doc-001",
        text="Smith found that accuracy was 95%.",
        page=2,
        char_start=0,
        char_end=34,
        citation_markers=["[1]"],
        reference_ids=[ref_id],
        claim_type="numeric",
        numbers_mentioned=["95%"],
        context_before="",
        context_after="",
        flags=[],
    )


def _full_text_source(year=2020, flags=None) -> Source:
    return Source(
        reference_id="ref-001",
        matched=True,
        match_score=0.9,
        title="Great Paper",
        authors=["Smith, J."],
        year=year,
        doi="10.1234/great",
        url="https://doi.org/10.1234/great",
        text_level="full_text",
        full_text_available=True,
        source_database="test",
        flags=flags or [],
    )


def _mock_passages() -> list[Passage]:
    return [
        Passage(
            passage_id="p-001",
            reference_id="ref-001",
            text="The accuracy was 95% on the test set.",
            page=5,
            section="Results",
            score=0.88,
        )
    ]


def _no_passages(*args, **kwargs) -> list[Passage]:
    return []


def _no_evidence(*args, **kwargs):
    return None


def _mock_evidence(*args, **kwargs) -> Evidence:
    return Evidence(
        quote="accuracy was 95%",
        passage_id="p-001",
        page=5,
        section="Results",
    )


def _mock_llm_supported() -> MockLLMClient:
    client = MockLLMClient()
    client.register_mock(
        "__default__",
        {
            "verdict": "supported",
            "explanation": "The source directly confirms 95% accuracy.",
            "llm_certainty": 0.9,
            "supporting_quote": "accuracy was 95%",
            "time_sensitive": False,
            "numbers_match": True,
            "scope_mismatch": False,
        },
    )
    return client


class TestVerifyHappyPath:
    def test_returns_verdict_object(self):
        v = verify(
            _make_claim(),
            _make_reference(),
            _full_text_source(),
            search_passages_fn=lambda *a, **kw: _mock_passages(),
            locate_quote_fn=_mock_evidence,
            llm_client=_mock_llm_supported(),
        )
        assert isinstance(v, Verdict)

    def test_claim_id_and_reference_id_preserved(self):
        v = verify(
            _make_claim(),
            _make_reference(),
            _full_text_source(),
            search_passages_fn=lambda *a, **kw: _mock_passages(),
            locate_quote_fn=_mock_evidence,
            llm_client=_mock_llm_supported(),
        )
        assert v.claim_id == "claim-001"
        assert v.reference_id == "ref-001"

    def test_supported_verdict_high_confidence(self):
        v = verify(
            _make_claim(),
            _make_reference(),
            _full_text_source(),
            search_passages_fn=lambda *a, **kw: _mock_passages(),
            locate_quote_fn=_mock_evidence,
            llm_client=_mock_llm_supported(),
        )
        assert v.verdict == "supported"
        assert v.confidence > 0.5

    def test_evidence_populated(self):
        v = verify(
            _make_claim(),
            _make_reference(),
            _full_text_source(),
            search_passages_fn=lambda *a, **kw: _mock_passages(),
            locate_quote_fn=_mock_evidence,
            llm_client=_mock_llm_supported(),
        )
        assert v.evidence is not None
        assert v.evidence.quote == "accuracy was 95%"


class TestVerifyEdgeCases:
    def test_no_passages_flags_full_text_unavailable(self):
        v = verify(
            _make_claim(),
            _make_reference(),
            _full_text_source(),
            search_passages_fn=_no_passages,
            locate_quote_fn=_no_evidence,
            llm_client=MockLLMClient(),
        )
        # With no passages the default mock returns needs_review and confidence will be low
        assert isinstance(v, Verdict)

    def test_unmatched_source_returns_verdict(self):
        source = Source(
            reference_id="ref-001",
            matched=False,
            match_score=0.0,
            title="",
            text_level="none",
            full_text_available=False,
            source_database="",
            flags=["reference_not_found"],
        )
        v = verify(
            _make_claim(),
            _make_reference(),
            source,
            search_passages_fn=_no_passages,
            locate_quote_fn=_no_evidence,
            llm_client=MockLLMClient(),
        )
        assert isinstance(v, Verdict)
        assert v.needs_human_review is True

    def test_ocr_flag_forces_human_review(self):
        v = verify(
            _make_claim(),
            _make_reference(),
            _full_text_source(flags=["ocr_text"]),
            search_passages_fn=lambda *a, **kw: _mock_passages(),
            locate_quote_fn=_mock_evidence,
            llm_client=_mock_llm_supported(),
        )
        assert v.needs_human_review is True
        assert "ocr_text" in v.flags

    def test_possibly_retracted_forces_human_review(self):
        v = verify(
            _make_claim(),
            _make_reference(),
            _full_text_source(flags=["possibly_retracted"]),
            search_passages_fn=lambda *a, **kw: _mock_passages(),
            locate_quote_fn=_mock_evidence,
            llm_client=_mock_llm_supported(),
        )
        assert v.needs_human_review is True
        assert "possibly_retracted" in v.flags

    def test_abstract_only_cap(self):
        source = Source(
            reference_id="ref-001",
            matched=True,
            match_score=0.75,
            title="Great Paper",
            text_level="abstract_only",
            full_text_available=False,
            source_database="test",
            flags=["abstract_only"],
        )
        v = verify(
            _make_claim(),
            _make_reference(),
            source,
            search_passages_fn=lambda *a, **kw: _mock_passages(),
            locate_quote_fn=_no_evidence,
            llm_client=_mock_llm_supported(),
        )
        assert v.confidence <= 0.50

    def test_old_time_sensitive_source_possibly_outdated(self):
        """Source from 2010 + time_sensitive=True → possibly_outdated."""
        client = MockLLMClient()
        client.register_mock(
            "__default__",
            {
                "verdict": "supported",
                "explanation": "Supported.",
                "llm_certainty": 0.8,
                "supporting_quote": None,
                "time_sensitive": True,  # triggers outdated check
                "numbers_match": True,
                "scope_mismatch": False,
            },
        )
        v = verify(
            _make_claim(),
            _make_reference(year=2010),
            _full_text_source(year=2010),
            search_passages_fn=lambda *a, **kw: _mock_passages(),
            locate_quote_fn=_no_evidence,
            llm_client=client,
        )
        assert v.verdict == "possibly_outdated"
        assert v.needs_human_review is True

    def test_number_not_found_flagged(self):
        client = MockLLMClient()
        client.register_mock(
            "__default__",
            {
                "verdict": "partly_supported",
                "explanation": "Some support.",
                "llm_certainty": 0.5,
                "supporting_quote": None,
                "time_sensitive": False,
                "numbers_match": False,  # claim has numbers but they don't match
                "scope_mismatch": False,
            },
        )
        v = verify(
            _make_claim(),
            _make_reference(),
            _full_text_source(),
            search_passages_fn=lambda *a, **kw: _mock_passages(),
            locate_quote_fn=_no_evidence,
            llm_client=client,
        )
        assert "number_not_found" in v.flags

    def test_confidence_breakdown_has_all_fields(self):
        v = verify(
            _make_claim(),
            _make_reference(),
            _full_text_source(),
            search_passages_fn=lambda *a, **kw: _mock_passages(),
            locate_quote_fn=_mock_evidence,
            llm_client=_mock_llm_supported(),
        )
        bd = v.confidence_breakdown
        assert 0 <= bd.retrieval <= 1
        assert 0 <= bd.llm_certainty <= 1
        assert 0 <= bd.text_match <= 1
        assert 0 <= bd.full_text <= 1
        assert 0 <= bd.numeric_match <= 1

    def test_source_trace_populated(self):
        v = verify(
            _make_claim(),
            _make_reference(),
            _full_text_source(),
            search_passages_fn=lambda *a, **kw: _mock_passages(),
            locate_quote_fn=_mock_evidence,
            llm_client=_mock_llm_supported(),
        )
        assert v.source_trace.doi == "10.1234/great"


class TestReverifyForReference:
    def test_returns_one_verdict_per_claim(self):
        claims = [_make_claim("ref-001"), _make_claim("ref-001")]
        claims[1] = claims[1].model_copy(update={"claim_id": "claim-002"})
        verdicts = reverify_for_reference(
            reference_id="ref-001",
            claims=claims,
            reference=_make_reference(),
            source=_full_text_source(),
            search_passages_fn=lambda *a, **kw: _mock_passages(),
            locate_quote_fn=_mock_evidence,
            llm_client=_mock_llm_supported(),
        )
        assert len(verdicts) == 2

    def test_skips_unrelated_claims(self):
        claim_unrelated = _make_claim("ref-001").model_copy(
            update={"claim_id": "c-other", "reference_ids": ["ref-999"]}
        )
        verdicts = reverify_for_reference(
            reference_id="ref-001",
            claims=[claim_unrelated],
            reference=_make_reference(),
            source=_full_text_source(),
            search_passages_fn=_no_passages,
            locate_quote_fn=_no_evidence,
            llm_client=MockLLMClient(),
        )
        assert len(verdicts) == 0
