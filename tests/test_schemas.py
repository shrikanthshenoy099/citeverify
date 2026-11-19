"""
tests/test_schemas.py – Smoke-tests for common/schemas.py.

Validates that every schema can be instantiated and serialised.
"""

from __future__ import annotations

import pytest
from citeverify_core.common.schemas import (
    BBox,
    Claim,
    ConfidenceBreakdown,
    Evidence,
    Flags,
    ParsedDocument,
    Passage,
    Reference,
    Review,
    Source,
    SourceTrace,
    Verdict,
)


def make_reference(ref_id: str = "ref-1") -> Reference:
    return Reference(
        reference_id=ref_id,
        raw_text="Smith (2020) Example Paper. Nature.",
        title="Example Paper",
        authors=["Smith, J."],
        year=2020,
        doi="10.1000/test",
        venue="Nature",
        parse_confidence=0.9,
    )


def make_claim(doc_id: str = "doc-1", ref_id: str = "ref-1") -> Claim:
    return Claim(
        claim_id="claim-1",
        doc_id=doc_id,
        text="Mortality was reduced by 42%.",
        page=1,
        section="Results",
        char_start=0,
        char_end=30,
        citation_markers=["Smith, 2020"],
        reference_ids=[ref_id],
        claim_type="numeric",
        numbers_mentioned=["42%"],
        context_before="In the trial,",
        context_after="p < 0.01.",
        flags=[],
    )


def make_verdict(claim_id: str = "claim-1", ref_id: str = "ref-1") -> Verdict:
    return Verdict(
        claim_id=claim_id,
        reference_id=ref_id,
        verdict="supported",
        explanation="The claim is directly supported.",
        evidence=None,
        confidence=0.85,
        confidence_breakdown=ConfidenceBreakdown(
            retrieval=0.9,
            llm_certainty=0.85,
            text_match=0.8,
            full_text=1.0,
            numeric_match=0.9,
        ),
        source_trace=SourceTrace(doi="10.1000/test", url=None, page=3, section="Results"),
        flags=[],
        needs_human_review=False,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_reference_roundtrip():
    ref = make_reference()
    assert Reference(**ref.model_dump()) == ref


def test_claim_roundtrip():
    claim = make_claim()
    assert Claim(**claim.model_dump()) == claim


def test_parsed_document():
    pd = ParsedDocument(
        doc_id="doc-1",
        source_type="pdf",
        num_pages=10,
        references=[make_reference()],
        claims=[make_claim()],
        warnings=[],
    )
    assert len(pd.references) == 1
    assert len(pd.claims) == 1


def test_source_defaults():
    source = Source(
        reference_id="ref-1",
        matched=False,
        match_score=0.0,
        source_database="crossref",
    )
    assert source.text_level == "none"
    assert source.full_text_available is False
    assert source.flags == []


def test_passage():
    p = Passage(
        passage_id="p-1",
        reference_id="ref-1",
        text="Sample text.",
        page=2,
        section="Methods",
        score=0.75,
    )
    assert p.score == 0.75


def test_evidence_with_bboxes():
    ev = Evidence(
        quote="Mortality was reduced by 42%.",
        passage_id="p-1",
        page=3,
        bboxes=[BBox(x0=10, y0=20, x1=200, y1=35)],
        page_width=595.0,
        page_height=842.0,
    )
    assert ev.bboxes[0].x0 == 10


def test_verdict_roundtrip():
    v = make_verdict()
    assert Verdict(**v.model_dump()) == v


def test_verdict_serialisation():
    v = make_verdict()
    j = v.model_dump_json()
    v2 = Verdict.model_validate_json(j)
    assert v2.verdict == "supported"
    assert v2.confidence == 0.85


def test_flags_constants():
    assert Flags.OCR_TEXT == "ocr_text"
    assert Flags.MANUAL_SOURCE == "manual_source"
    assert Flags.POSSIBLY_RETRACTED == "possibly_retracted"
    assert Flags.LOW_RETRIEVAL_SCORE == "low_retrieval_score"


def test_review():
    r = Review(
        review_id="rv-1",
        claim_id="claim-1",
        reference_id="ref-1",
        action="accept",
        new_verdict=None,
        comment="Looks correct.",
        reviewer="Alice",
        timestamp="2024-01-01T12:00:00+00:00",
    )
    assert r.action == "accept"
