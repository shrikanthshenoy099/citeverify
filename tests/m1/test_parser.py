"""
tests/m1/test_parser.py – tests for doc_intel/parser.py (parse_document).

Covers:
  - Pasted text (plain string) round-trip
  - PDF path routing (no real PDF needed; exercises error path + mock)
  - Unsupported file type returns empty ParsedDocument with warning
  - Sentence segmentation populates claims
  - reference_list_not_found warning when ref section absent
  - References and claims populated when ref section present
  - parse_document raises ValueError when both inputs are None
  - Page map is None for pasted text
  - Doc ID is preserved in output and claim IDs
"""

from __future__ import annotations

import os
import pytest

os.environ.setdefault("LLM_PROVIDER", "mock")

from citeverify_core.doc_intel.parser import parse_document
from citeverify_core.common.schemas import ParsedDocument


# ---------------------------------------------------------------------------
# Pasted text – happy path
# ---------------------------------------------------------------------------

class TestPastedText:
    def test_returns_parsed_document(self, text_with_refs: str) -> None:
        result = parse_document(file_path=None, raw_text=text_with_refs, doc_id="doc-001")
        assert isinstance(result, ParsedDocument)

    def test_source_type_is_text(self, text_with_refs: str) -> None:
        result = parse_document(file_path=None, raw_text=text_with_refs, doc_id="doc-001")
        assert result.source_type == "text"

    def test_num_pages_is_none_for_text(self, text_with_refs: str) -> None:
        result = parse_document(file_path=None, raw_text=text_with_refs, doc_id="doc-001")
        assert result.num_pages is None

    def test_doc_id_preserved(self, text_with_refs: str) -> None:
        result = parse_document(file_path=None, raw_text=text_with_refs, doc_id="my-doc-42")
        assert result.doc_id == "my-doc-42"

    def test_claims_populated(self, text_with_refs: str) -> None:
        result = parse_document(file_path=None, raw_text=text_with_refs, doc_id="doc-001")
        assert len(result.claims) > 0

    def test_claim_doc_id_matches(self, text_with_refs: str) -> None:
        result = parse_document(file_path=None, raw_text=text_with_refs, doc_id="doc-001")
        for claim in result.claims:
            assert claim.doc_id == "doc-001"

    def test_claim_ids_are_unique(self, text_with_refs: str) -> None:
        result = parse_document(file_path=None, raw_text=text_with_refs, doc_id="doc-001")
        ids = [c.claim_id for c in result.claims]
        assert len(ids) == len(set(ids))

    def test_claim_id_contains_doc_id(self, text_with_refs: str) -> None:
        result = parse_document(file_path=None, raw_text=text_with_refs, doc_id="doc-001")
        for claim in result.claims:
            assert "doc-001" in claim.claim_id

    def test_references_populated_when_ref_section_present(self, text_with_refs: str) -> None:
        result = parse_document(file_path=None, raw_text=text_with_refs, doc_id="doc-001")
        assert len(result.references) > 0

    def test_no_refs_warning_when_absent(self, text_no_refs: str) -> None:
        result = parse_document(file_path=None, raw_text=text_no_refs, doc_id="doc-001")
        assert "reference_list_not_found" in result.warnings

    def test_no_no_refs_warning_when_present(self, text_with_refs: str) -> None:
        result = parse_document(file_path=None, raw_text=text_with_refs, doc_id="doc-001")
        assert "reference_list_not_found" not in result.warnings

    def test_claim_char_offsets_are_valid(self, text_with_refs: str) -> None:
        result = parse_document(file_path=None, raw_text=text_with_refs, doc_id="doc-001")
        for claim in result.claims:
            assert claim.char_start >= 0
            assert claim.char_end > claim.char_start

    def test_claim_page_is_none_for_text(self, text_with_refs: str) -> None:
        result = parse_document(file_path=None, raw_text=text_with_refs, doc_id="doc-001")
        for claim in result.claims:
            assert claim.page is None

    def test_empty_text_produces_no_claims(self) -> None:
        result = parse_document(file_path=None, raw_text="   ", doc_id="doc-001")
        assert result.claims == []


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

class TestInputValidation:
    def test_raises_when_both_none(self) -> None:
        with pytest.raises(ValueError, match="file_path or raw_text"):
            parse_document(file_path=None, raw_text=None, doc_id="doc-001")

    def test_unsupported_file_type_returns_warning(self, tmp_path) -> None:
        f = tmp_path / "doc.rtf"
        f.write_text("hello")
        result = parse_document(file_path=str(f), raw_text=None, doc_id="doc-001")
        assert any("unsupported_file_type" in w for w in result.warnings)
        assert result.claims == []
        assert result.references == []

    def test_missing_pdf_returns_error_warning(self, tmp_path) -> None:
        result = parse_document(
            file_path=str(tmp_path / "nonexistent.pdf"),
            raw_text=None,
            doc_id="doc-001",
        )
        assert any("pdf_extraction_error" in w for w in result.warnings)
        assert result.source_type == "pdf"


# ---------------------------------------------------------------------------
# Author-year citation style
# ---------------------------------------------------------------------------

class TestAuthorYearStyle:
    def test_parses_author_year_references(self, text_author_year: str) -> None:
        result = parse_document(file_path=None, raw_text=text_author_year, doc_id="doc-ay")
        assert len(result.references) >= 1

    def test_author_year_markers_detected(self, text_author_year: str) -> None:
        result = parse_document(file_path=None, raw_text=text_author_year, doc_id="doc-ay")
        all_markers = [m for c in result.claims for m in c.citation_markers]
        assert len(all_markers) > 0
