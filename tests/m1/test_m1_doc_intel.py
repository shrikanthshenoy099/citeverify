"""
tests/test_m1_doc_intel.py – pytest suite for M1 Document Intelligence.

Run from the citeverify/ root:
    cd citeverify
    PYTHONPATH=backend pytest tests/test_m1_doc_intel.py -v

These tests run without installing OCR engines or PyMuPDF, exercising the
parsers via plain text inputs and mocks where needed.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup – add backend to sys.path so imports resolve in a bare checkout.
# ---------------------------------------------------------------------------
BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

SAMPLE_TEXT_WITH_REFS = """\
This study demonstrates that transformer models outperform RNNs on most NLP tasks [1].
Specifically, BERT achieved 93.5% accuracy on the GLUE benchmark, a 4.2% improvement [2].
We therefore conclude that pre-training on large corpora is essential for downstream performance [1, 2].
The dataset used follows the protocol described by Smith and Jones [3].

REFERENCES

[1] Devlin, J., Chang, M.-W., Lee, K., & Toutanova, K. (2019). BERT: Pre-training of Deep
    Bidirectional Transformers for Language Understanding. arXiv:1810.04805.
[2] Wang, A. et al. (2018). GLUE: A Multi-Task Benchmark. doi:10.18653/v1/W18-5446.
[3] Smith, R. & Jones, B. (2020). "Dataset Construction for NLP". Journal of AI, 5(2), 100-120.
"""

SAMPLE_TEXT_NO_REFS = """\
Sentence one is a short intro.
Sentence two has a numeric claim: accuracy was 95.1% [1].
Final conclusion: this proves the method works.
"""


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestSchemas:
    def test_reference_model(self):
        from citeverify_core.common.schemas import Reference
        ref = Reference(
            reference_id="doc1_ref_0000",
            raw_text="Some raw text",
            title="A Title",
            authors=["Smith, R."],
            year=2020,
            doi="10.1234/test",
            venue="Journal",
            parse_confidence=0.85,
        )
        assert ref.reference_id == "doc1_ref_0000"
        assert ref.parse_confidence == 0.85

    def test_claim_model(self):
        from citeverify_core.common.schemas import Claim
        claim = Claim(
            claim_id="doc1_claim_0000",
            doc_id="doc1",
            text="Accuracy was 95.1%.",
            page=1,
            section="Results",
            char_start=0,
            char_end=20,
            citation_markers=["[1]"],
            reference_ids=["doc1_ref_0000"],
            claim_type="numeric",
            numbers_mentioned=["95.1%"],
            context_before="",
            context_after="",
            flags=[],
        )
        assert claim.claim_type == "numeric"
        assert claim.numbers_mentioned == ["95.1%"]

    def test_parsed_document_model(self):
        from citeverify_core.common.schemas import ParsedDocument
        pd = ParsedDocument(doc_id="d1", source_type="text", num_pages=None)
        assert pd.claims == []
        assert pd.references == []
        assert pd.warnings == []

    def test_flags_constants(self):
        from citeverify_core.common.schemas import Flags
        assert Flags.OCR_TEXT == "ocr_text"
        assert Flags.NO_CITATION == "no_citation"
        assert Flags.MANUAL_SOURCE == "manual_source"


# ---------------------------------------------------------------------------
# ref_parser tests
# ---------------------------------------------------------------------------

class TestRefParser:
    def test_parse_numbered_references(self):
        from citeverify_core.doc_intel.ref_parser import parse_references
        refs = parse_references(SAMPLE_TEXT_WITH_REFS, "doc1")
        assert len(refs) >= 2
        # All have a reference_id and raw_text
        for ref in refs:
            assert ref.reference_id.startswith("doc1_ref_")
            assert len(ref.raw_text) > 5

    def test_parse_confidence_range(self):
        from citeverify_core.doc_intel.ref_parser import parse_references
        refs = parse_references(SAMPLE_TEXT_WITH_REFS, "doc1")
        for ref in refs:
            assert 0.0 <= ref.parse_confidence <= 1.0

    def test_doi_extracted(self):
        from citeverify_core.doc_intel.ref_parser import parse_references
        refs = parse_references(SAMPLE_TEXT_WITH_REFS, "doc1")
        dois = [r.doi for r in refs if r.doi]
        assert len(dois) >= 1

    def test_no_reference_section(self):
        from citeverify_core.doc_intel.ref_parser import parse_references
        refs = parse_references("Just some plain text without any bibliography.", "doc2")
        assert refs == []

    def test_ocr_confidence_penalty(self):
        from citeverify_core.doc_intel.ref_parser import parse_references
        refs_no_ocr = parse_references(SAMPLE_TEXT_WITH_REFS, "doc1", ocr_page_indices=frozenset())
        refs_ocr = parse_references(SAMPLE_TEXT_WITH_REFS, "doc1", ocr_page_indices=frozenset({0}))
        # Every reference should have lower or equal confidence under OCR penalty
        for r_no, r_ocr in zip(refs_no_ocr, refs_ocr):
            assert r_ocr.parse_confidence <= r_no.parse_confidence


# ---------------------------------------------------------------------------
# claim_extractor tests
# ---------------------------------------------------------------------------

class TestClaimExtractor:
    def _get_sentences_and_offsets(self, text: str):
        import pysbd
        seg = pysbd.Segmenter(language="en", clean=False)
        sentences = seg.segment(text)
        offsets = []
        cursor = 0
        for s in sentences:
            idx = text.find(s, cursor)
            if idx == -1:
                idx = cursor
            offsets.append((idx, idx + len(s)))
            cursor = idx + len(s)
        return sentences, offsets

    def test_basic_claim_extraction(self):
        from citeverify_core.doc_intel.claim_extractor import extract_claims
        text = SAMPLE_TEXT_NO_REFS
        sents, offsets = self._get_sentences_and_offsets(text)
        claims = extract_claims(
            sentences=sents,
            char_offsets=offsets,
            page_map=[None] * len(sents),
            section_map=[None] * len(sents),
            ref_index={"[1]": "doc1_ref_0000"},
            doc_id="doc1",
        )
        assert len(claims) >= 1
        # claim IDs are unique
        ids = [c.claim_id for c in claims]
        assert len(ids) == len(set(ids))

    def test_citation_marker_linked(self):
        from citeverify_core.doc_intel.claim_extractor import extract_claims
        text = "The model achieved 93.5% accuracy on the GLUE benchmark [1]."
        sents, offsets = self._get_sentences_and_offsets(text)
        ref_index = {"[1]": "doc1_ref_0000"}
        claims = extract_claims(
            sentences=sents,
            char_offsets=offsets,
            page_map=[None],
            section_map=[None],
            ref_index=ref_index,
            doc_id="doc1",
        )
        assert any("[1]" in c.citation_markers for c in claims)
        assert any("doc1_ref_0000" in c.reference_ids for c in claims)

    def test_no_citation_flag(self):
        from citeverify_core.doc_intel.claim_extractor import extract_claims
        from citeverify_core.common.schemas import Flags
        text = "This study demonstrates that transformers work well."
        sents, offsets = self._get_sentences_and_offsets(text)
        claims = extract_claims(
            sentences=sents,
            char_offsets=offsets,
            page_map=[None],
            section_map=[None],
            ref_index={},
            doc_id="doc1",
        )
        for c in claims:
            assert Flags.NO_CITATION in c.flags

    def test_ocr_text_flag(self):
        from citeverify_core.doc_intel.claim_extractor import extract_claims
        from citeverify_core.common.schemas import Flags
        text = "The model achieved 93.5% accuracy on the GLUE benchmark, a significant result."
        sents, offsets = self._get_sentences_and_offsets(text)
        claims = extract_claims(
            sentences=sents,
            char_offsets=offsets,
            page_map=[None],
            section_map=[None],
            ref_index={},
            doc_id="doc1",
            ocr_sentence_indices=frozenset({0}),
        )
        assert any(Flags.OCR_TEXT in c.flags for c in claims)

    def test_numeric_claim_type(self):
        from citeverify_core.doc_intel.claim_extractor import extract_claims, _classify_claim
        assert _classify_claim("BERT achieved 93.5% accuracy, a 4.2% improvement.") == "numeric"

    def test_conclusion_claim_type(self):
        from citeverify_core.doc_intel.claim_extractor import _classify_claim
        assert _classify_claim("We therefore conclude that pre-training is essential.") == "conclusion"

    def test_numbers_mentioned(self):
        from citeverify_core.doc_intel.claim_extractor import extract_claims
        text = "The transformer model achieved 93.5% accuracy on 1200 benchmark examples [1]."
        sents, offsets = self._get_sentences_and_offsets(text)
        claims = extract_claims(
            sentences=sents,
            char_offsets=offsets,
            page_map=[None],
            section_map=[None],
            ref_index={},
            doc_id="doc1",
        )
        assert len(claims) > 0
        nums = claims[0].numbers_mentioned
        assert "93.5" in nums or "93.5%" in nums


# ---------------------------------------------------------------------------
# parse_document integration (plain text path, no I/O)
# ---------------------------------------------------------------------------

class TestParseDocumentText:
    def test_text_input_returns_parsed_document(self):
        from citeverify_core.doc_intel.parser import parse_document
        result = parse_document(file_path=None, raw_text=SAMPLE_TEXT_WITH_REFS, doc_id="test_doc")
        assert result.doc_id == "test_doc"
        assert result.source_type == "text"
        assert result.num_pages is None
        assert isinstance(result.claims, list)
        assert isinstance(result.references, list)

    def test_text_produces_claims(self):
        from citeverify_core.doc_intel.parser import parse_document
        result = parse_document(file_path=None, raw_text=SAMPLE_TEXT_WITH_REFS, doc_id="test_doc2")
        assert len(result.claims) >= 2

    def test_text_produces_references(self):
        from citeverify_core.doc_intel.parser import parse_document
        result = parse_document(file_path=None, raw_text=SAMPLE_TEXT_WITH_REFS, doc_id="test_doc3")
        assert len(result.references) >= 2

    def test_no_reference_section_gives_warning(self):
        from citeverify_core.doc_intel.parser import parse_document
        result = parse_document(file_path=None, raw_text=SAMPLE_TEXT_NO_REFS, doc_id="test_doc4")
        assert any("no_references_found" in w for w in result.warnings)

    def test_raises_when_no_input(self):
        from citeverify_core.doc_intel.parser import parse_document
        with pytest.raises(ValueError):
            parse_document(file_path=None, raw_text=None, doc_id="test_doc5")

    def test_claim_ids_unique(self):
        from citeverify_core.doc_intel.parser import parse_document
        result = parse_document(file_path=None, raw_text=SAMPLE_TEXT_WITH_REFS, doc_id="uid_doc")
        ids = [c.claim_id for c in result.claims]
        assert len(ids) == len(set(ids))

    def test_reference_ids_unique(self):
        from citeverify_core.doc_intel.parser import parse_document
        result = parse_document(file_path=None, raw_text=SAMPLE_TEXT_WITH_REFS, doc_id="uid_doc2")
        ids = [r.reference_id for r in result.references]
        assert len(ids) == len(set(ids))

    def test_char_offsets_within_text(self):
        from citeverify_core.doc_intel.parser import parse_document
        text = SAMPLE_TEXT_WITH_REFS
        result = parse_document(file_path=None, raw_text=text, doc_id="offset_doc")
        for claim in result.claims:
            assert claim.char_start >= 0
            assert claim.char_end > claim.char_start
            assert claim.char_end <= len(text)


# ---------------------------------------------------------------------------
# OCR module tests (mocked – no real OCR engine needed)
# ---------------------------------------------------------------------------

class TestOCRModule:
    def test_ocr_pdf_page_returns_string_on_missing_fitz(self):
        """If fitz is not installed, ocr_pdf_page returns empty string without crashing."""
        with patch.dict("sys.modules", {"fitz": None}):
            # Force reimport
            import importlib
            import citeverify_core.common.ocr as ocr_mod
            importlib.reload(ocr_mod)
            result = ocr_mod.ocr_pdf_page("/nonexistent/file.pdf", 0)
            assert isinstance(result, str)

    def test_ocr_returns_empty_string_on_bad_path(self):
        """ocr_pdf_page should return '' for a file that doesn't exist, not raise."""
        from citeverify_core.common.ocr import ocr_pdf_page
        result = ocr_pdf_page("/nonexistent/definitely_missing_12345.pdf", 0)
        assert result == ""
