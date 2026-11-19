"""
verification/engine.py – Core verification logic for M3.

Public interface (called by M4 orchestrator):

    verify(claim, reference, source) -> Verdict

The engine:
  1. Calls M2's search_passages to retrieve relevant passages.
  2. Optionally calls M2's locate_quote to find the best evidence passage + bboxes.
  3. Sends a prompt to the LLM via llm_client.complete_json().
  4. Applies the possibly_outdated override.
  5. Computes the weighted confidence score.
  6. Collects flags and decides whether human review is required.
  7. Returns a fully populated Verdict.

Re-running verify() for the same (claim, reference) pair is safe and idempotent —
M4 may call it again after a manual source upload (see M3 Addendum §4).
"""

from __future__ import annotations

import logging
import uuid
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
# M2 interface stubs (injected at runtime or imported directly)
# ---------------------------------------------------------------------------
# The engine imports M2 lazily to avoid circular imports and to remain testable
# with mock passage providers.  At runtime M4 may also inject passage providers
# via the optional keyword arguments on verify().

_M2_AVAILABLE = False

try:
    from citeverify_core.retrieval import search_passages as _search_passages  # type: ignore
    from citeverify_core.retrieval import locate_quote as _locate_quote        # type: ignore
    _M2_AVAILABLE = True
except ImportError:
    logger.warning(
        "citeverify_core.retrieval not importable; verify() will run with empty passages. "
        "This is expected during M3 development before M2 is integrated."
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
# Public verify() function
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
    search_passages_fn: Optional override for M2's search_passages (for testing).
    locate_quote_fn:    Optional override for M2's locate_quote (for testing).
    llm_client:         Optional LLMClient override (for testing).

    Returns
    -------
    A fully populated Verdict.  Never raises — on failure returns a
    'needs_review' verdict with appropriate flags.
    """
    _search = search_passages_fn or _default_search_passages
    _locate = locate_quote_fn or _default_locate_quote
    _llm = llm_client or get_llm_client()

    flags: list[str] = list(source.flags)  # start with M2 flags on the source
    evidence: Optional[Evidence] = None

    # ── 1. Retrieve relevant passages ───────────────────────────────────────
    passages: list[Passage] = []
    top_retrieval_score = 0.0

    if source.matched and source.text_level in ("full_text", "abstract_only"):
        try:
            passages = _search(reference.reference_id, claim.text, k=5)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "search_passages failed for reference %s: %s", reference.reference_id, exc
            )

    if passages:
        top_retrieval_score = max(p.score for p in passages)
    else:
        logger.debug(
            "No passages retrieved for reference %s; claim %s will be low-confidence.",
            reference.reference_id, claim.claim_id,
        )
        if source.matched and source.full_text_available:
            if "full_text_unavailable" not in flags:
                flags.append("full_text_unavailable")

    # ── 2. Call LLM ─────────────────────────────────────────────────────────
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
    numbers_match = True  # default to True when no numbers mentioned

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
        ) = parse_llm_response(llm_data)
        llm_valid = True

    except LLMSchemaError as exc:
        logger.error(
            "LLM returned invalid schema for claim %s / ref %s: %s",
            claim.claim_id, reference.reference_id, exc,
        )
        flags.append("llm_output_invalid")

    except LLMError as exc:
        logger.error(
            "LLM error for claim %s / ref %s: %s",
            claim.claim_id, reference.reference_id, exc,
        )

    # ── 3. Special-flag handling ─────────────────────────────────────────────
    # ocr_text: force human review and note in explanation
    if "ocr_text" in flags:
        if explanation and llm_valid:
            explanation += " (Note: source text was obtained via OCR and may be less reliable.)"

    # possibly_retracted: mention in explanation, force human review
    if "possibly_retracted" in flags:
        if explanation and llm_valid:
            explanation += (
                " WARNING: This source may have been retracted. "
                "Human review is mandatory."
            )

    # manual_source: treat as normal full-text (no special override needed per addendum)

    # ── 4. Apply possibly_outdated override ──────────────────────────────────
    if llm_valid:
        verdict_label = maybe_override_possibly_outdated(
            verdict=verdict_label,  # type: ignore[arg-type]
            source_year=source.year or reference.year,
            time_sensitive=time_sensitive,
        )

    # ── 5. Locate evidence quote ─────────────────────────────────────────────
    text_match_score = 0.0
    if supporting_quote and source.text_level in ("full_text",):
        try:
            evidence = _locate(reference.reference_id, supporting_quote)
            if evidence is not None:
                text_match_score = 1.0
            else:
                flags.append("quote_not_verified")
                text_match_score = 0.3  # LLM found it but fuzzy match failed
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "locate_quote failed for reference %s: %s", reference.reference_id, exc
            )
            flags.append("quote_not_verified")
    elif supporting_quote:
        # abstract_only or metadata_only: cannot verify bbox, but record quote
        evidence = Evidence(
            quote=supporting_quote,
            passage_id=passages[0].passage_id if passages else "unknown",
            page=passages[0].page if passages else None,
            section=passages[0].section if passages else None,
        )
        text_match_score = 0.5  # partial credit

    # ── 6. Numeric check ─────────────────────────────────────────────────────
    if claim.numbers_mentioned and not numbers_match:
        if "number_not_found" not in flags:
            flags.append("number_not_found")

    # ── 7. Compute confidence ────────────────────────────────────────────────
    overall_confidence, breakdown = compute_confidence(
        retrieval_score=top_retrieval_score,
        llm_certainty=llm_certainty,
        text_match_score=text_match_score,
        source=source,
        numbers_match=numbers_match,
        flags=flags,
        verdict=verdict_label,
    )

    # ── 8. Human review gate ─────────────────────────────────────────────────
    needs_review_flag = requires_human_review(
        confidence=overall_confidence,
        verdict=verdict_label,
        flags=flags,
    )

    # ── 9. Source trace ──────────────────────────────────────────────────────
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
    Re-run verify() for every (claim, reference) pair that involves *reference_id*.

    Called by M4 after a manual source PDF is uploaded via
    POST /api/references/{reference_id}/source.

    Parameters
    ----------
    reference_id: The reference whose source has been updated.
    claims:       All claims that cite this reference (filtered by M4).
    reference:    The Reference object.
    source:       The newly ingested Source (from M2.ingest_pdf).
    **verify_kwargs: Forwarded to verify() (e.g. llm_client override for tests).

    Returns
    -------
    List of fresh Verdicts, one per claim.
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
