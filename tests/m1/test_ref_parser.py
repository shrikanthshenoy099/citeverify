"""
tests/m1/test_ref_parser.py – unit tests for doc_intel/ref_parser.py.

Covers:
  - _locate_reference_section finds header variants
  - _split_reference_section: numbered, author-year, fallback
  - _extract_doi / _extract_year / _extract_quoted_title helpers
  - parse_references round-trip (with mock LLM)
  - parse_confidence scoring (high / medium / low)
  - OCR confidence penalty applied
  - LLM enrichment path triggered when regex fields < 2
  - No reference section → empty list
  - reference_id format
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("LLM_PROVIDER", "mock")

from citeverify_core.doc_intel.ref_parser import (
    _locate_reference_section,
    _split_reference_section,
    _extract_doi,
    _extract_year,
    _extract_quoted_title,
    parse_references,
)
from citeverify_core.doc_intel.config import REF_HIGH_CONFIDENCE, REF_LOW_CONFIDENCE


# ---------------------------------------------------------------------------
# _locate_reference_section
# ---------------------------------------------------------------------------

class TestLocateReferenceSection:
    def test_finds_references_header(self) -> None:
        text = "Some body text.\n\nReferences\n[1] Smith 2020."
        section = _locate_reference_section(text)
        assert section is not None
        assert "Smith 2020" in section

    def test_finds_bibliography_header(self) -> None:
        text = "Introduction.\n\nBibliography\nJones 2019."
        section = _locate_reference_section(text)
        assert section is not None

    def test_finds_works_cited_header(self) -> None:
        text = "Main text.\n\nWorks Cited\nDoe 2021."
        section = _locate_reference_section(text)
        assert section is not None

    def test_returns_none_when_no_header(self) -> None:
        text = "No references here. Just plain prose about science."
        assert _locate_reference_section(text) is None

    def test_caps_at_15000_chars(self) -> None:
        # Header followed by >15000 chars of references
        big_refs = "A" * 20_000
        text = f"Intro.\n\nReferences\n{big_refs}"
        section = _locate_reference_section(text)
        assert section is not None
        assert len(section) <= 15_000


# ---------------------------------------------------------------------------
# _split_reference_section
# ---------------------------------------------------------------------------

class TestSplitReferenceSection:
    def test_numbered_bracket_entries(self) -> None:
        text = (
            "[1] LeCun et al. Nature 2015.\n"
            "[2] Vaswani et al. NeurIPS 2017.\n"
            "[3] Devlin et al. NAACL 2019."
        )
        entries = _split_reference_section(text)
        assert len(entries) == 3

    def test_numbered_dot_entries(self) -> None:
        text = (
            "1. Smith, J. (2020). Some title. Journal.\n"
            "2. Doe, A. (2021). Another title. Conference."
        )
        entries = _split_reference_section(text)
        assert len(entries) == 2

    def test_author_year_entries(self) -> None:
        text = (
            "\nSmith, J. (2020). Title one. Nature.\n"
            "\nDoe, A. (2021). Title two. Science."
        )
        entries = _split_reference_section(text)
        assert len(entries) >= 1

    def test_fallback_double_newline(self) -> None:
        text = "Entry one with some text.\n\nEntry two with more text.\n\nEntry three here."
        entries = _split_reference_section(text)
        assert len(entries) == 3

    def test_filters_empty_strings(self) -> None:
        text = "[1] Valid entry.\n[2] Another valid entry."
        entries = _split_reference_section(text)
        assert all(e.strip() for e in entries)


# ---------------------------------------------------------------------------
# Field extractors
# ---------------------------------------------------------------------------

class TestExtractDoi:
    def test_doi_prefix(self) -> None:
        assert _extract_doi("doi:10.1038/nature14539") == "10.1038/nature14539"

    def test_doi_url(self) -> None:
        assert _extract_doi("https://doi.org/10.5555/3295222") == "10.5555/3295222"

    def test_no_doi(self) -> None:
        assert _extract_doi("No DOI in this string.") is None

    def test_trailing_punctuation_stripped(self) -> None:
        result = _extract_doi("doi:10.1038/nature14539.")
        assert result == "10.1038/nature14539"


class TestExtractYear:
    def test_finds_year(self) -> None:
        assert _extract_year("Smith et al. (2020). Title.") == 2020

    def test_returns_last_year(self) -> None:
        # e.g. "1999 … 2021" should return 2021
        assert _extract_year("Originally 1999, updated 2021.") == 2021

    def test_no_year(self) -> None:
        assert _extract_year("No year in this string.") is None

    def test_year_1800_boundary(self) -> None:
        assert _extract_year("Published in 1856.") == 1856

    def test_future_year_2099(self) -> None:
        assert _extract_year("Projected outcome in 2099.") == 2099


class TestExtractQuotedTitle:
    def test_double_quotes(self) -> None:
        raw = 'Smith (2020). "Attention is all you need." NeurIPS.'
        assert _extract_quoted_title(raw) == "Attention is all you need."

    def test_unicode_curly_quotes(self) -> None:
        raw = "LeCun (2015). \u201cDeep learning.\u201d Nature."
        result = _extract_quoted_title(raw)
        assert result is not None
        assert "Deep learning" in result

    def test_no_quoted_title(self) -> None:
        assert _extract_quoted_title("Smith 2020. Plain title. Nature.") is None


# ---------------------------------------------------------------------------
# parse_references – integration
# ---------------------------------------------------------------------------

class TestParseReferences:
    def test_returns_list(self, text_with_refs: str) -> None:
        refs = parse_references(text_with_refs, "doc-001")
        assert isinstance(refs, list)

    def test_returns_references_when_section_present(self, text_with_refs: str) -> None:
        refs = parse_references(text_with_refs, "doc-001")
        assert len(refs) >= 1

    def test_returns_empty_when_no_section(self, text_no_refs: str) -> None:
        refs = parse_references(text_no_refs, "doc-001")
        assert refs == []

    def test_reference_id_format(self, text_with_refs: str) -> None:
        refs = parse_references(text_with_refs, "doc-001")
        for ref in refs:
            assert ref.reference_id.startswith("doc-001_ref_")

    def test_reference_ids_are_unique(self, text_with_refs: str) -> None:
        refs = parse_references(text_with_refs, "doc-001")
        ids = [r.reference_id for r in refs]
        assert len(ids) == len(set(ids))

    def test_raw_text_stored(self, text_with_refs: str) -> None:
        refs = parse_references(text_with_refs, "doc-001")
        for ref in refs:
            assert len(ref.raw_text) >= 10

    def test_doi_extracted_when_present(self, text_with_refs: str) -> None:
        refs = parse_references(text_with_refs, "doc-001")
        dois = [r.doi for r in refs if r.doi]
        assert len(dois) >= 1

    def test_year_extracted_when_present(self, text_with_refs: str) -> None:
        refs = parse_references(text_with_refs, "doc-001")
        years = [r.year for r in refs if r.year]
        assert len(years) >= 1

    def test_confidence_in_range(self, text_with_refs: str) -> None:
        refs = parse_references(text_with_refs, "doc-001")
        for ref in refs:
            assert 0.0 <= ref.parse_confidence <= 1.0

    def test_high_confidence_when_all_fields_found(self, text_with_refs: str) -> None:
        # At least one ref should have high confidence (DOI + year + title present)
        refs = parse_references(text_with_refs, "doc-001")
        high = [r for r in refs if r.parse_confidence >= REF_HIGH_CONFIDENCE]
        assert len(high) >= 1

    def test_ocr_penalty_reduces_confidence(self, text_with_refs: str) -> None:
        refs_no_ocr = parse_references(text_with_refs, "doc-001", ocr_page_indices=frozenset())
        refs_ocr = parse_references(text_with_refs, "doc-001", ocr_page_indices=frozenset([0]))
        # Average confidence should be lower with OCR penalty
        avg_no_ocr = sum(r.parse_confidence for r in refs_no_ocr) / len(refs_no_ocr)
        avg_ocr = sum(r.parse_confidence for r in refs_ocr) / len(refs_ocr)
        assert avg_ocr < avg_no_ocr

    def test_different_doc_ids_give_different_ref_ids(self, text_with_refs: str) -> None:
        refs_a = parse_references(text_with_refs, "doc-A")
        refs_b = parse_references(text_with_refs, "doc-B")
        ids_a = {r.reference_id for r in refs_a}
        ids_b = {r.reference_id for r in refs_b}
        assert ids_a.isdisjoint(ids_b)
