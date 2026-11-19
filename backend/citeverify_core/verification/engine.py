"""
verification/engine.py – Core verification logic for M3.

Public interface (called by M4 orchestrator):

    verify(claim, reference, source) -> Verdict

Pipeline
--------
1. Early exit if source not matched (no LLM call).
2. Retrieve passages from M2.search_passages.
3. Apply low_retrieval_score / possibly_unrelated_citation flags.
4. Call LLM with up to 2 retries on schema-invalid JSON.
5. Apply scope_mismatch cap (supported -> partly_supported at most).
6. Apply possibly_outdated override.
7. Anti-hallucination: verify supporting quote with M2.locate_quote;
   if not found and quote is not an exact substring of retrieved text,
   flag quote_not_verified and downgrade supported/partly_supported -> needs_review.
8. Numeric check: flag number_not_found when numbers are mentioned but LLM says no match;
   if verdict was 'supported' downgrade to 'partly_supported'.
9. Compute weighted confidence.
10. Apply needs_human_review gate.
11. Build source trace and return Verdict.

Re-running verify() for the same (claim, reference) pair is safe and idempotent.
M4 calls it again after a manual source upload (see reverify_for_reference).
"""

from __future__ import annotations

import logging
from typing import Optional

from citeverify_core.common.llm_client import LLMError, LLMSchemaError, get_llm_client
from citeverify_core.common.schemas import (
    Claim,
    Evidence,
    Passage,
    Reference,
    Source,
    SourceTrace,
    Verdict,
)
from citeverify_core.verification import config
from citeverify_core.verification.confidence import (
    compute_confidence,
    requires_human_review,
)
from citeverify_core.verification.verdict import (
    LLM_RESPONSE_SCHEMA,
    build_prompts,
    maybe_override_possibly_outdated,
    parse_llm_response,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# M2 lazy import with graceful fallback
# ---------------------------------------------------------------------------

_M2_AVAILABLE = False
try:
    from citeverify_core.retrieval import search_passages as _search_passages  # type: ignore
    from citeverify_core.retrieval import locate_quote as _locate_quote        # type: ignore
    _M2_AVAILABLE = True
except ImportError:
    logger.warning(
        "citeverify_core.retrieval not importable; verify() will run with empty passages. "
        "Expected during M3 development before M2 is merged."
    )


def _default_search_passages(reference_id: str, query: str, k: int = 5) -> list[Passage]:
    if _M2_AVAILABLE:
        return _search_passages(reference_id, query, k)
    return []


def _default_locate_quote(reference_id: str, quote: str) -> Optional[Evidence]:
    if _M2_AVAILABLE:
        return _locate_quote(reference_id, quote)
    return None


# ---------------------------------------------------------------------------
# Constants / helpers
# ---------------------------------------------------------------------------

_VERDICTS_SUPPORTING = {"supported", "partly_supported"}
_LLM_MAX_RETRIES = 2  # max extra attempts on schema-invalid JSON


def _quote_in_passages(quote: str, passages: list[Passage]) -> bool:
    """Return True if *quote* is an exact substring of any retrieved passage."""
    q = quote.lower()
    return any(q in p.text.lower() for p in passages)


def _make_unmatched_verdict(claim: Claim, reference: Reference, flags: list[str]) -> Verdict:
    """Return a fast needs_review Verdict without calling the LLM (source not matched)."""
    source_stub = Source(
        reference_id=reference.reference_id,
        matched=False,
        match_score=0.0,
        title="",
        text_level="none",
        full_text_available=False,
        source_database="",
        flags=flags,
    )
    overall, breakdown = compute_confidence(
        retrieval_score=0.0,
        llm_certainty=0.0,
        text_match_score=0.0,
        source=source_stub,
        numbers_match=True,
        flags=flags,
        verdict="needs_review",
    )
    return Verdict(
        claim_id=claim.claim_id,
        reference_id=reference.reference_id,
        verdict="needs_review",
        explanation="Source could not be retrieved; human review required.",
        evidence=None,
        confidence=overall,
        confidence_breakdown=breakdown,
        source_trace=SourceTrace(
            doi=reference.doi,
            url=None,
            page=None,
            section=None,
        ),
        flags=flags,
        needs_human_review=True,
    )


# ---------------------------------------------------------------------------
# Public verify()
# ---------------------------------------------------------------------------


def verify(
    claim: Claim,
    reference: Reference,
    source: Source,
    *,
    search_passages_fn=None,
    locate_quote_fn=None,
    llm_client=None,
) -> Verdict:
    """
    Verify a single (claim, reference) pair and return a Verdict.

    Parameters
    ----------
    claim:              The claim to verify.
    reference:          The Reference the claim cites.
    source:             The retrieved Source for that reference (from M2).
    search_passages_fn: Optional override for M2.search_passages (testing).
    locate_quote_fn:    Optional override for M2.locate_quote (testing).
    llm_client:         Optional LLMClient override (testing).

    Returns
    -------
    A fully populated Verdict.  Never raises.
    """
    _search = search_passages_fn or _default_search_passages
    _locate = locate_quote_fn or _default_locate_quote
    _llm = llm_client or get_llm_client()

    flags: list[str] = list(source.flags)

    # -- Step 1: Early exit if source not matched ----------------------------
    if not source.matched:
        if "reference_not_found" not in flags:
            flags.append("reference_not_found")
        logger.debug(
            "Source not matched for ref=%s; returning needs_review without LLM call.",
            reference.reference_id,
        )
        return _make_unmatched_verdict(claim, reference, flags)

    evidence: Optional[Evidence] = None

    # -- Step 2: Retrieve passages -------------------------------------------
    passages: list[Passage] = []
    top_retrieval_score = 0.0

    if source.text_level in ("full_text", "abstract_only"):
        try:
            passages = _search(reference.reference_id, claim.text, k=5)
        except Exception as exc:  # noqa: BLE001
            logger.warning("search_passages failed for ref=%s: %s", reference.reference_id, exc)

    if passages:
        top_retrieval_score = max(p.score for p in passages)
    else:
        if source.full_text_available and "full_text_unavailable" not in flags:
            flags.append("full_text_unavailable")

    # -- Step 3: Retrieval quality flags ------------------------------------
    # NOTE: M2 uses BM25 scores.  The low_retrieval_score threshold (0.35) was
    # calibrated for cosine similarity [0,1].  Until M2 confirms its score range,
    # this comparison is best-effort.  Adjust CV_LOW_RETRIEVAL_THRESHOLD once M2
    # normalises BM25 output.  See integration risk note in README.
    if passages and top_retrieval_score < config.LOW_RETRIEVAL_SCORE_THRESHOLD:
        if "low_retrieval_score" not in flags:
            flags.append("low_retrieval_score")
        if top_retrieval_score < config.LOW_RETRIEVAL_SCORE_THRESHOLD * 0.5:
            if "possibly_unrelated_citation" not in flags:
                flags.append("possibly_unrelated_citation")

    # -- Step 4: Call LLM (up to _LLM_MAX_RETRIES extra attempts) -----------
    system_prompt, user_prompt = build_prompts(
        claim=claim,
        reference=reference,
        source=source,
        passages=[p.text for p in passages],
    )

    llm_valid = False
    verdict_label = "needs_review"
    explanation = "LLM analysis unavailable; human review required."
    llm_certainty = 0.0
    supporting_quote: Optional[str] = None
    time_sensitive = False
    numbers_match = True
    scope_mismatch = False

    llm_attempts = 0
    max_attempts = 1 + _LLM_MAX_RETRIES
    while llm_attempts < max_attempts:
        llm_attempts += 1
        try:
            llm_data = _llm.complete_json(
                system=system_prompt,
                user=user_prompt,
                schema=LLM_RESPONSE_SCHEMA,
                temperature=0,
            )
            (
                verdict_label,
                explanation,
                llm_certainty,
                supporting_quote,
                time_sensitive,
                numbers_match,
                scope_mismatch,
            ) = parse_llm_response(llm_data)
            llm_valid = True
            break

        except LLMSchemaError as exc:
            logger.warning(
                "LLM schema error (attempt %d/%d) for claim=%s ref=%s: %s",
                llm_attempts, max_attempts, claim.claim_id, reference.reference_id, exc,
            )
            if llm_attempts >= max_attempts:
                flags.append("llm_output_invalid")

        except LLMError as exc:
            logger.error(
                "LLM error for claim=%s ref=%s: %s",
                claim.claim_id, reference.reference_id, exc,
            )
            break  # non-retryable

    # -- Step 5: Scope mismatch cap -----------------------------------------
    if scope_mismatch:
        if "scope_mismatch" not in flags:
            flags.append("scope_mismatch")
        if verdict_label == "supported":
            verdict_label = "partly_supported"
            explanation += " (Note: scope mismatch detected -- verdict capped at partly_supported.)"

    # -- Step 6: Special flag handling --------------------------------------
    if "ocr_text" in flags and llm_valid:
        explanation += " (Note: source text obtained via OCR and may be less reliable.)"

    if "possibly_retracted" in flags and llm_valid:
        explanation += (
            " WARNING: This source may have been retracted. Human review is mandatory."
        )

    # -- Step 7: Apply possibly_outdated override ---------------------------
    if llm_valid:
        verdict_label = maybe_override_possibly_outdated(
            verdict=verdict_label,  # type: ignore[arg-type]
            source_year=source.year or reference.year,
            time_sensitive=time_sensitive,
        )

    # -- Step 8: Anti-hallucination quote verification ---------------------
    text_match_score = 0.0
    if supporting_quote and source.text_level == "full_text":
        try:
            evidence = _locate(reference.reference_id, supporting_quote)
            if evidence is not None:
                text_match_score = 1.0
            else:
                if _quote_in_passages(supporting_quote, passages):
                    text_match_score = 0.6
                    flags.append("quote_not_verified")
                else:
                    # Quote not found in source or passages: hallucination risk
                    flags.append("quote_not_verified")
                    text_match_score = 0.0
                    if verdict_label in _VERDICTS_SUPPORTING:
                        logger.warning(
                            "Quote not found by locate_quote or in passages; "
                            "downgrading verdict %r -> needs_review for claim=%s ref=%s",
                            verdict_label, claim.claim_id, reference.reference_id,
                        )
                        verdict_label = "needs_review"
                        explanation += (
                            " (Caution: the supporting quote could not be verified in the "
                            "source text. Verdict downgraded to needs_review.)"
                        )
        except Exception as exc:  # noqa: BLE001
            logger.warning("locate_quote failed for ref=%s: %s", reference.reference_id, exc)
            flags.append("quote_not_verified")

    elif supporting_quote:
        # abstract_only or metadata_only: cannot verify bbox, record as unverified quote
        evidence = Evidence(
            quote=supporting_quote,
            passage_id=passages[0].passage_id if passages else "unknown",
            page=passages[0].page if passages else None,
            section=passages[0].section if passages else None,
        )
        text_match_score = 0.5
        flags.append("quote_not_verified")

    # -- Step 9: Numeric check ---------------------------------------------
    if claim.numbers_mentioned and not numbers_match:
        if "number_not_found" not in flags:
            flags.append("number_not_found")
        if verdict_label == "supported":
            verdict_label = "partly_supported"
            explanation += " (Note: key numbers from the claim were not found in the source.)"

    # -- Step 10: Confidence -----------------------------------------------
    overall_confidence, breakdown = compute_confidence(
        retrieval_score=top_retrieval_score,
        llm_certainty=llm_certainty,
        text_match_score=text_match_score,
        source=source,
        numbers_match=numbers_match,
        flags=flags,
        verdict=verdict_label,
    )

    # -- Step 11: Human review gate ----------------------------------------
    needs_review_flag = requires_human_review(
        confidence=overall_confidence,
        verdict=verdict_label,
        flags=flags,
    )

    # -- Step 12: Source trace --------------------------------------------
    source_trace = SourceTrace(
        doi=source.doi or reference.doi,
        url=source.url,
        page=evidence.page if evidence else None,
        section=evidence.section if evidence else (passages[0].section if passages else None),
    )

    return Verdict(
        claim_id=claim.claim_id,
        reference_id=reference.reference_id,
        verdict=verdict_label,  # type: ignore[arg-type]
        explanation=explanation,
        evidence=evidence,
        confidence=overall_confidence,
        confidence_breakdown=breakdown,
        source_trace=source_trace,
        flags=flags,
        needs_human_review=needs_review_flag,
    )


# ---------------------------------------------------------------------------
# reverify_for_reference helper (M3 Addendum §4)
# ---------------------------------------------------------------------------

def reverify_for_reference(
    reference_id: str,
    claims: list[Claim],
    reference: Reference,
    source: Source,
    **verify_kwargs,
) -> list[Verdict]:
    """
    Re-run verify() for every claim that cites *reference_id*.

    Safe to call multiple times -- verify() is idempotent.
    Called by M4 after a manual source PDF is uploaded via
    POST /api/references/{reference_id}/source.
    """
    results: list[Verdict] = []
    for claim in claims:
        if reference_id not in claim.reference_ids:
            continue
        verdict = verify(claim, reference, source, **verify_kwargs)
        results.append(verdict)
        logger.info(
            "reverify: claim=%s ref=%s verdict=%s confidence=%.2f",
            claim.claim_id, reference_id, verdict.verdict, verdict.confidence,
        )
    return results
