"""
tests/test_mocks.py – Tests for the mock pipeline (M4).

Verifies the mock implementations conform to the data contracts.
"""

from __future__ import annotations

import os
import pytest

# Ensure mock mode is active
os.environ["USE_MOCKS"] = "true"

from citeverify_core.common.schemas import ParsedDocument, Source, Verdict
from app.mocks import mock_parse_document, mock_retrieve_source, mock_verify


def test_mock_parse_document_returns_valid_schema():
    result = mock_parse_document(file_path=None, raw_text="Some text.", doc_id="test-doc")
    assert isinstance(result, ParsedDocument)
    assert result.doc_id == "test-doc"
    assert len(result.references) >= 1
    assert len(result.claims) >= 1
    for claim in result.claims:
        for ref_id in claim.reference_ids:
            assert any(r.reference_id == ref_id for r in result.references), (
                f"claim.reference_id {ref_id!r} not found in references"
            )


def test_mock_retrieve_source_returns_valid_schema():
    from app.mocks import mock_parse_document
    parsed = mock_parse_document(file_path=None, raw_text="Text", doc_id="doc-x")
    ref = parsed.references[0]
    source = mock_retrieve_source(ref)
    assert isinstance(source, Source)
    assert source.reference_id == ref.reference_id
    assert 0.0 <= source.match_score <= 1.0


def test_mock_verify_returns_valid_verdict():
    parsed = mock_parse_document(file_path=None, raw_text="Text", doc_id="doc-y")
    claim = parsed.claims[0]
    ref = parsed.references[0]
    source = mock_retrieve_source(ref)
    verdict = mock_verify(claim, ref, source)
    assert isinstance(verdict, Verdict)
    assert verdict.claim_id == claim.claim_id
    assert verdict.reference_id == ref.reference_id
    assert 0.0 <= verdict.confidence <= 1.0
    assert verdict.verdict in {
        "supported", "partly_supported", "unsupported",
        "contradictory", "possibly_outdated", "needs_review",
    }


def test_mock_verify_needs_human_review():
    parsed = mock_parse_document(file_path=None, raw_text="Text", doc_id="doc-z")
    claim = parsed.claims[0]
    ref = parsed.references[0]
    source = mock_retrieve_source(ref)
    verdict = mock_verify(claim, ref, source)
    # Mock always returns low confidence → should require human review
    assert verdict.needs_human_review is True
