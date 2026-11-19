"""
tests/m1/test_claim_extractor.py – unit tests for doc_intel/claim_extractor.py.

Covers:
  - Citation marker extraction: numeric [N], ranges (expanded), en-dash, semicolon-separated,
    author-year (Smith, 2020), (Smith et al., 2020), narrative form Smith et al. (2020),
    year suffix (2020a), ampersand, deduplication
  - Claim type classification (numeric, conclusion, methodological, factual)
  - is_checkable filter (short sentences, headings, URLs)
  - no_citation / reference_not_found flags
  - ocr_text flag for OCR sentences
  - reference_id resolution via ref_index (now returns tuple)
  - context window (before/after)
  - LLM batch classification: mock path and fallback
  - Claim struct fields
"""

from __future__ import annotations

import os

os.environ.setdefault("LLM_PROVIDER", "mock")

from citeverify_core.doc_intel.claim_extractor import (
    extract_claims,
    _extract_citation_markers,
    _expand_numeric_marker,
    _classify_claim,
    _is_checkable,
    _markers_to_ref_ids,
)
from citeverify_core.common.schemas import Flags


# ---------------------------------------------------------------------------
# _expand_numeric_marker
# ---------------------------------------------------------------------------

class TestExpandNumericMarker:
    def test_single_number_unchanged(self) -> None:
        assert _expand_numeric_marker("[1]") == ["[1]"]

    def test_range_expanded(self) -> None:
        assert _expand_numeric_marker("[1-4]") == ["[1]", "[2]", "[3]", "[4]"]

    def test_comma_list_expanded(self) -> None:
        assert _expand_numeric_marker("[1,3]") == ["[1]", "[3]"]

    def test_mixed_range_and_single(self) -> None:
        result = _expand_numeric_marker("[1,3-5]")
        assert result == ["[1]", "[3]", "[4]", "[5]"]

    def test_paren_range_expanded(self) -> None:
        assert _expand_numeric_marker("(1-3)") == ["(1)", "(2)", "(3)"]


# ---------------------------------------------------------------------------
# _extract_citation_markers
# ---------------------------------------------------------------------------

class TestExtractCitationMarkers:
    # --- Numeric ---
    def test_numeric_bracket(self) -> None:
        assert "[1]" in _extract_citation_markers("accuracy was 95% [1].")

    def test_numeric_paren(self) -> None:
        assert "(2)" in _extract_citation_markers("see results (2).")

    def test_numeric_range_expanded(self) -> None:
        markers = _extract_citation_markers("as shown [1-3]")
        assert markers == ["[1]", "[2]", "[3]"]

    def test_numeric_range_en_dash(self) -> None:
        # en-dash U+2013
        markers = _extract_citation_markers("results [1\u20134]")
        assert markers == ["[1]", "[2]", "[3]", "[4]"]

    def test_numeric_comma_list_expanded(self) -> None:
        markers = _extract_citation_markers("prior work [1,2,3]")
        assert markers == ["[1]", "[2]", "[3]"]

    def test_mixed_range_and_single(self) -> None:
        markers = _extract_citation_markers("see [1,3-5]")
        assert "[1]" in markers
        assert "[3]" in markers and "[4]" in markers and "[5]" in markers

    # --- Author-year ---
    def test_author_year_no_comma(self) -> None:
        markers = _extract_citation_markers("as argued (Smith 2020).")
        assert "(Smith 2020)" in markers

    def test_author_year_comma(self) -> None:
        markers = _extract_citation_markers("see (Smith, 2020).")
        assert "(Smith, 2020)" in markers

    def test_author_year_et_al(self) -> None:
        markers = _extract_citation_markers("proposed by (Jones et al., 2021).")
        assert "(Jones et al., 2021)" in markers

    def test_author_year_ampersand(self) -> None:
        markers = _extract_citation_markers("see (Brown & Lee, 2019).")
        assert "(Brown & Lee, 2019)" in markers

    def test_author_year_suffix(self) -> None:
        markers = _extract_citation_markers("see (Smith 2020a).")
        assert "(Smith 2020a)" in markers

    def test_semicolon_separated(self) -> None:
        markers = _extract_citation_markers("as shown (Smith, 2020; Jones, 2019).")
        assert "(Smith, 2020)" in markers
        assert "(Jones, 2019)" in markers

    def test_narrative_form(self) -> None:
        # Smith et al. (2020) → canonical "(Smith et al., 2020)"
        markers = _extract_citation_markers("Smith et al. (2020) demonstrated this.")
        assert any("Smith" in m and "2020" in m for m in markers), f"got: {markers}"

    def test_no_markers(self) -> None:
        assert _extract_citation_markers("No citations in this sentence.") == []

    def test_deduplicates(self) -> None:
        markers = _extract_citation_markers("[1] and [1] again.")
        assert markers.count("[1]") == 1


# ---------------------------------------------------------------------------
# _classify_claim
# ---------------------------------------------------------------------------

class TestClassifyClaim:
    def test_numeric_with_signal(self) -> None:
        t = "The accuracy increased by 15% over the baseline."
        assert _classify_claim(t) == "numeric"

    def test_conclusion_signal(self) -> None:
        t = "Therefore, we conclude that transformers outperform RNNs."
        assert _classify_claim(t) == "conclusion"

    def test_methodological_signal(self) -> None:
        t = "We trained the model on the benchmark dataset using the proposed algorithm."
        assert _classify_claim(t) == "methodological"

    def test_fallback_factual(self) -> None:
        t = "The authors published their findings in an open-access journal."
        assert _classify_claim(t) == "factual"

    def test_number_without_signal_is_not_numeric(self) -> None:
        t = "There are 42 papers in the survey."
        result = _classify_claim(t)
        assert result in ("factual", "methodological", "conclusion")


# ---------------------------------------------------------------------------
# _is_checkable
# ---------------------------------------------------------------------------

class TestIsCheckable:
    def test_normal_sentence_passes(self) -> None:
        assert _is_checkable("Deep learning has achieved remarkable results in NLP.") is True

    def test_too_short_fails(self) -> None:
        assert _is_checkable("OK.") is False

    def test_pure_url_fails(self) -> None:
        assert _is_checkable("https://example.com/paper.pdf") is False

    def test_heading_like_fails(self) -> None:
        assert _is_checkable("INTRODUCTION") is False

    def test_whitespace_only_fails(self) -> None:
        assert _is_checkable("    ") is False


# ---------------------------------------------------------------------------
# _markers_to_ref_ids  (returns (ids, unresolved) tuple since B.13 fix)
# ---------------------------------------------------------------------------

class TestMarkersToRefIds:
    def test_resolves_known_marker(self) -> None:
        index = {"[1]": "doc_ref_0000", "[2]": "doc_ref_0001"}
        ids, unresolved = _markers_to_ref_ids(["[1]"], index)
        assert ids == ["doc_ref_0000"]
        assert unresolved == []

    def test_unknown_marker_returns_unresolved(self) -> None:
        index = {"[1]": "doc_ref_0000"}
        ids, unresolved = _markers_to_ref_ids(["[99]"], index)
        assert ids == []
        assert unresolved == ["[99]"]

    def test_deduplicates_ids(self) -> None:
        index = {"[1]": "doc_ref_0000", "(1)": "doc_ref_0000"}
        ids, unresolved = _markers_to_ref_ids(["[1]", "(1)"], index)
        assert ids == ["doc_ref_0000"]
        assert unresolved == []

    def test_empty_markers(self) -> None:
        ids, unresolved = _markers_to_ref_ids([], {"[1]": "doc_ref_0000"})
        assert ids == []
        assert unresolved == []

    def test_mixed_resolved_and_unresolved(self) -> None:
        index = {"[1]": "ref-001"}
        ids, unresolved = _markers_to_ref_ids(["[1]", "[99]"], index)
        assert ids == ["ref-001"]
        assert unresolved == ["[99]"]


# ---------------------------------------------------------------------------
# extract_claims – integration
# ---------------------------------------------------------------------------

class TestExtractClaims:
    def _run(
        self,
        sentences: list[str],
        ref_index: dict[str, str] | None = None,
        ocr_set: frozenset[int] | None = None,
    ):
        offsets = [(i * 100, i * 100 + len(s)) for i, s in enumerate(sentences)]
        page_map = [None] * len(sentences)
        section_map = [None] * len(sentences)
        return extract_claims(
            sentences=sentences,
            char_offsets=offsets,
            page_map=page_map,
            section_map=section_map,
            ref_index=ref_index or {},
            doc_id="test-doc",
            ocr_sentence_indices=ocr_set,
        )

    def test_returns_claims_list(self) -> None:
        sents = ["This model achieves 95% accuracy on the benchmark dataset [1]."]
        claims = self._run(sents)
        assert isinstance(claims, list)
        assert len(claims) == 1

    def test_no_citation_flag_when_no_markers(self) -> None:
        sents = ["The proposed framework improves performance significantly."]
        claims = self._run(sents)
        assert Flags.NO_CITATION in claims[0].flags

    def test_no_citation_flag_absent_when_markers_present(self) -> None:
        sents = ["The accuracy improved by 10% [1]."]
        claims = self._run(sents, ref_index={"[1]": "ref-001"})
        assert Flags.NO_CITATION not in claims[0].flags

    def test_reference_not_found_flag_for_unresolved(self) -> None:
        # [99] is not in the ref index → reference_not_found
        sents = ["The accuracy improved by 10% [99]."]
        claims = self._run(sents, ref_index={"[1]": "ref-001"})
        assert Flags.REFERENCE_NOT_FOUND in claims[0].flags

    def test_ocr_flag_set_for_ocr_sentence(self) -> None:
        sents = [
            "Normal sentence about the experiment design and training protocol.",
            "This sentence came from an OCR page and contains a 15% improvement.",
        ]
        claims = self._run(sents, ocr_set=frozenset([1]))
        ocr_claims = [c for c in claims if Flags.OCR_TEXT in c.flags]
        assert len(ocr_claims) == 1

    def test_reference_ids_resolved(self) -> None:
        sents = ["The model accuracy increased by 15% [1]."]
        claims = self._run(sents, ref_index={"[1]": "doc-001_ref_0000"})
        assert claims[0].reference_ids == ["doc-001_ref_0000"]

    def test_range_markers_resolve_to_multiple_ids(self) -> None:
        # [1-3] expands → [1],[2],[3] → resolves to 3 ref IDs
        ref_index = {"[1]": "ref-001", "[2]": "ref-002", "[3]": "ref-003"}
        sents = ["Prior work demonstrated this improvement [1-3]."]
        claims = self._run(sents, ref_index=ref_index)
        assert len(claims) == 1
        assert set(claims[0].reference_ids) == {"ref-001", "ref-002", "ref-003"}

    def test_claim_id_sequential(self) -> None:
        sents = [
            "The accuracy improved by 10% [1].",
            "Therefore we conclude that the method works well.",
            "The dataset contains 50000 annotated training examples.",
        ]
        claims = self._run(sents)
        for i, claim in enumerate(claims):
            assert f"_claim_{i:04d}" in claim.claim_id

    def test_numbers_mentioned_extracted(self) -> None:
        sents = ["The accuracy increased by 15% over the 2019 baseline."]
        claims = self._run(sents)
        assert "15" in claims[0].numbers_mentioned or "15%" in claims[0].numbers_mentioned

    def test_context_before_and_after(self) -> None:
        sents = [
            "Prior work achieved 90% accuracy in this domain.",
            "The proposed method reaches 95% accuracy on the benchmark.",
            "This outperforms all previous baseline models.",
        ]
        claims = self._run(sents)
        middle = [c for c in claims if "95%" in c.text]
        assert len(middle) == 1
        assert "90%" in middle[0].context_before
        assert "outperforms" in middle[0].context_after

    def test_short_sentences_filtered_out(self) -> None:
        sents = ["OK.", "This model achieves 95% accuracy on the standard benchmark."]
        claims = self._run(sents)
        texts = [c.text for c in claims]
        assert not any(t == "OK." for t in texts)

    def test_char_offsets_stored(self) -> None:
        sents = ["The accuracy of the proposed model improved by 20%."]
        claims = self._run(sents)
        assert claims[0].char_start == 0
        assert claims[0].char_end > 0

    def test_near_duplicate_removed(self) -> None:
        # Exact same sentence appearing twice should produce only one claim
        s = "The model accuracy improved by 15% over the baseline."
        claims = self._run([s, s])
        assert len(claims) == 1

    def test_30pct_example_sentence(self) -> None:
        """B.21: the problem-statement example sentence."""
        sents = ["A particular study found that a learning app improved test scores by 30%."]
        claims = self._run(sents)
        assert len(claims) == 1
        assert claims[0].claim_type == "numeric"
        assert "30%" in claims[0].numbers_mentioned
