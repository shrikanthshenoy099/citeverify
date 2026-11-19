"""
app/mocks.py – Mock implementations of M1, M2, M3 for integration testing
              before teammates' real code is merged.

These are ONLY used when USE_MOCKS=true (the default for initial setup).
"""

from __future__ import annotations

from typing import Optional

from citeverify_core.common.schemas import (
    BBox,
    Claim,
    ConfidenceBreakdown,
    Evidence,
    ParsedDocument,
    Passage,
    Reference,
    Source,
    SourceTrace,
    Verdict,
)


# ---------------------------------------------------------------------------
# M1 mock
# ---------------------------------------------------------------------------

def mock_parse_document(
    file_path: Optional[str],
    raw_text: Optional[str],
    doc_id: str,
) -> ParsedDocument:
    """
    Return a richer ParsedDocument with four claims covering the demo scenarios:
      1. Correct citation with numeric claim
      2. Partly-supported claim (mismatched stat)
      3. Fake/mismatched citation
      4. Uncited statistic (no citation → no_citation flag + needs_review)
    """
    ref1 = Reference(
        reference_id=f"{doc_id}-ref-1",
        raw_text="Smith J, Doe A. Example Paper. Nature. 2020;42:1-10. doi:10.1000/example",
        title="Example Paper",
        authors=["Smith, J.", "Doe, A."],
        year=2020,
        doi="10.1000/example",
        venue="Nature",
        parse_confidence=0.9,
    )
    ref2 = Reference(
        reference_id=f"{doc_id}-ref-2",
        raw_text="Jones K. Another Study. JAMA. 2015;10:55-62.",
        title="Another Study",
        authors=["Jones, K."],
        year=2015,
        doi=None,
        venue="JAMA",
        parse_confidence=0.75,
    )
    ref3 = Reference(
        reference_id=f"{doc_id}-ref-3",
        raw_text="Green P. Fabricated Results. Lancet. 2021;300:1.",
        title="Fabricated Results",
        authors=["Green, P."],
        year=2021,
        doi="10.1000/fake",
        venue="Lancet",
        parse_confidence=0.6,
    )

    claim1 = Claim(
        claim_id=f"{doc_id}-claim-1",
        doc_id=doc_id,
        text="The intervention reduced mortality by 42% (Smith et al., 2020).",
        page=1,
        section="Results",
        char_start=0,
        char_end=65,
        citation_markers=["Smith et al., 2020"],
        reference_ids=[ref1.reference_id],
        claim_type="numeric",
        numbers_mentioned=["42%"],
        context_before="In a randomised controlled trial of 500 participants,",
        context_after="This was statistically significant (p < 0.01).",
        flags=[],
    )
    claim2 = Claim(
        claim_id=f"{doc_id}-claim-2",
        doc_id=doc_id,
        text="Previous work showed no significant effect (Jones, 2015).",
        page=2,
        section="Introduction",
        char_start=200,
        char_end=258,
        citation_markers=["Jones, 2015"],
        reference_ids=[ref2.reference_id],
        claim_type="factual",
        numbers_mentioned=[],
        context_before="In contrast to recent findings,",
        context_after="However, methodology differed substantially.",
        flags=[],
    )
    claim3 = Claim(
        claim_id=f"{doc_id}-claim-3",
        doc_id=doc_id,
        text="Green et al. (2021) reported a 95% cure rate in all patients.",
        page=3,
        section="Discussion",
        char_start=400,
        char_end=465,
        citation_markers=["Green et al., 2021"],
        reference_ids=[ref3.reference_id],
        claim_type="numeric",
        numbers_mentioned=["95%"],
        context_before="Contrary to our findings,",
        context_after="This result has not been replicated.",
        flags=[],
    )
    claim4 = Claim(
        claim_id=f"{doc_id}-claim-4",
        doc_id=doc_id,
        text="Overall, 73% of studies in this field suffer from publication bias.",
        page=4,
        section="Conclusion",
        char_start=600,
        char_end=665,
        citation_markers=[],
        reference_ids=[],       # intentionally uncited
        claim_type="conclusion",
        numbers_mentioned=["73%"],
        context_before="Based on a review of the literature,",
        context_after="Further investigation is warranted.",
        flags=[],
    )

    return ParsedDocument(
        doc_id=doc_id,
        source_type="pdf" if (file_path and file_path.endswith(".pdf")) else "text",
        num_pages=4 if file_path else None,
        references=[ref1, ref2, ref3],
        claims=[claim1, claim2, claim3, claim4],
        warnings=["[MOCK] Document parsed by mock – no real analysis performed."],
    )


# ---------------------------------------------------------------------------
# M2 mocks
# ---------------------------------------------------------------------------

def mock_retrieve_source(reference: Reference) -> Source:
    """Return a stub Source marked as metadata_only."""
    return Source(
        reference_id=reference.reference_id,
        matched=True,
        match_score=0.75,
        title=reference.title or "Unknown Title",
        authors=reference.authors,
        year=reference.year,
        doi=reference.doi,
        url=f"https://doi.org/{reference.doi}" if reference.doi else None,
        pdf_path=None,
        text_level="metadata_only",
        full_text_available=False,
        source_database="mock",
        flags=["full_text_unavailable"],
    )


def mock_search_passages(reference_id: str, query: str, k: int = 5) -> list[Passage]:
    return [
        Passage(
            passage_id=f"{reference_id}-p1",
            reference_id=reference_id,
            text="[MOCK] The intervention reduced mortality by 42 per cent.",
            page=3,
            section="Results",
            score=0.82,
        )
    ]


def mock_locate_quote(reference_id: str, quote: str) -> Optional[Evidence]:
    return None


# ---------------------------------------------------------------------------
# M3 mock
# ---------------------------------------------------------------------------

# Cycle through different verdicts so the UI demo shows all badge colours
_MOCK_VERDICT_CYCLE = [
    ("partly_supported", 0.62),
    ("supported", 0.88),
    ("unsupported", 0.45),
    ("contradictory", 0.20),
    ("possibly_outdated", 0.55),
    ("needs_review", 0.30),
]
_mock_verdict_counter: list[int] = [0]


def mock_verify(claim: Claim, reference: Reference, source: Source) -> Verdict:
    """
    Return a richer stub Verdict that exercises the full UI.

    - Cycles through all six verdict labels so every badge colour is visible.
    - The first call includes mock Evidence with page, section, and bboxes so
      the PdfHighlightViewer can be tested even without a real PDF.
    """
    idx = _mock_verdict_counter[0] % len(_MOCK_VERDICT_CYCLE)
    _mock_verdict_counter[0] += 1
    verdict_label, confidence = _MOCK_VERDICT_CYCLE[idx]

    # Provide mock evidence with bboxes on the first verdict so the highlight
    # viewer has data to render (even though there is no real PDF).
    evidence: Optional[Evidence] = None
    if idx == 0:
        evidence = Evidence(
            quote="The intervention reduced mortality by 42 per cent in the treatment arm.",
            passage_id=f"{reference.reference_id}-p1",
            page=3,
            section="Results",
            bboxes=[
                BBox(x0=72.0, y0=320.5, x1=524.0, y1=334.0),
                BBox(x0=72.0, y0=334.0, x1=380.0, y1=347.5),
            ],
            page_width=595.0,
            page_height=842.0,
        )

    needs_review = (
        confidence < 0.60
        or verdict_label in ("needs_review", "contradictory", "possibly_outdated")
    )

    return Verdict(
        claim_id=claim.claim_id,
        reference_id=reference.reference_id,
        verdict=verdict_label,  # type: ignore[arg-type]
        explanation=(
            f"[MOCK] Verdict '{verdict_label}' – confidence {confidence:.0%}. "
            "No real verification was performed. Human review required."
        ),
        evidence=evidence,
        confidence=confidence,
        confidence_breakdown=ConfidenceBreakdown(
            retrieval=min(1.0, confidence + 0.10),
            llm_certainty=confidence,
            text_match=max(0.0, confidence - 0.05),
            full_text=0.4 if source.text_level == "abstract_only" else (0.0 if source.text_level == "none" else confidence),
            numeric_match=confidence if claim.claim_type == "numeric" else 0.0,
        ),
        source_trace=SourceTrace(
            doi=source.doi,
            url=source.url,
            page=evidence.page if evidence else None,
            section=evidence.section if evidence else None,
        ),
        flags=source.flags.copy(),
        needs_human_review=needs_review,
    )
