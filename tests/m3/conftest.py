"""
tests/m3/conftest.py – Shared fixtures for M3 tests.
"""

from __future__ import annotations

import os

import pytest

# Force mock LLM for all M3 tests
os.environ.setdefault("LLM_PROVIDER", "mock")

from citeverify_core.common.llm_client import MockLLMClient
from citeverify_core.common.schemas import Claim, Evidence, Passage, Reference, Source


# ---------------------------------------------------------------------------
# Minimal valid objects
# ---------------------------------------------------------------------------


@pytest.fixture()
def basic_reference() -> Reference:
    return Reference(
        reference_id="ref-001",
        raw_text="Smith et al. (2020) Some Important Finding. Nature, 123.",
        title="Some Important Finding",
        authors=["Smith, J.", "Doe, A."],
        year=2020,
        doi="10.1038/test.001",
        venue="Nature",
        parse_confidence=0.9,
    )


@pytest.fixture()
def basic_claim(basic_reference: Reference) -> Claim:
    return Claim(
        claim_id="claim-001",
        doc_id="doc-001",
        text="Smith et al. (2020) found that the accuracy was 95%.",
        page=3,
        section="Results",
        char_start=0,
        char_end=54,
        citation_markers=["[1]"],
        reference_ids=["ref-001"],
        claim_type="numeric",
        numbers_mentioned=["95%"],
        context_before="Prior work achieved 90%.",
        context_after="This outperforms baseline.",
        flags=[],
    )


@pytest.fixture()
def full_text_source(basic_reference: Reference) -> Source:
    return Source(
        reference_id="ref-001",
        matched=True,
        match_score=0.92,
        title="Some Important Finding",
        authors=["Smith, J.", "Doe, A."],
        year=2020,
        doi="10.1038/test.001",
        url="https://doi.org/10.1038/test.001",
        pdf_path=None,
        text_level="full_text",
        full_text_available=True,
        source_database="semantic_scholar",
        flags=[],
    )


@pytest.fixture()
def abstract_only_source(basic_reference: Reference) -> Source:
    return Source(
        reference_id="ref-001",
        matched=True,
        match_score=0.75,
        title="Some Important Finding",
        authors=["Smith, J.", "Doe, A."],
        year=2020,
        doi="10.1038/test.001",
        url="https://doi.org/10.1038/test.001",
        pdf_path=None,
        text_level="abstract_only",
        full_text_available=False,
        source_database="crossref",
        flags=["abstract_only"],
    )


@pytest.fixture()
def unmatched_source() -> Source:
    return Source(
        reference_id="ref-001",
        matched=False,
        match_score=0.0,
        title="",
        authors=[],
        year=None,
        doi=None,
        url=None,
        pdf_path=None,
        text_level="none",
        full_text_available=False,
        source_database="",
        flags=["reference_not_found"],
    )


@pytest.fixture()
def mock_llm() -> MockLLMClient:
    return MockLLMClient()


@pytest.fixture()
def mock_passages(basic_reference: Reference) -> list[Passage]:
    return [
        Passage(
            passage_id="p-001",
            reference_id="ref-001",
            text="The model achieved an accuracy of 95% on the benchmark dataset.",
            page=5,
            section="Results",
            score=0.88,
        )
    ]
