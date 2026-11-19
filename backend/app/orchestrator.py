"""
app/orchestrator.py – pipeline orchestrator (M4).

Runs the full pipeline for one document:
  M1 parse_document → M2 retrieve_source + search_passages → M3 verify

Also handles re-verification after a manual source upload
(POST /api/references/{reference_id}/source).

All work happens synchronously inside a thread-pool executor so the
async FastAPI event loop is not blocked.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Optional

from citeverify_core.common.schemas import (
    Claim,
    ParsedDocument,
    Reference,
    Source,
    Verdict,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports for M1 / M2 / M3  (they may not all be installed yet during
# individual-module development; we degrade gracefully with warnings).
# ---------------------------------------------------------------------------

def _import_parse_document():
    try:
        from citeverify_core.doc_intel import parse_document
        return parse_document
    except ImportError as exc:
        logger.error("[M4] citeverify_core.doc_intel not available: %s", exc)
        return None


def _import_m2():
    """Returns (retrieve_source, search_passages, locate_quote, ingest_pdf) or Nones."""
    try:
        from citeverify_core.retrieval import (  # type: ignore
            retrieve_source,
            search_passages,
            locate_quote,
            ingest_pdf,
        )
        return retrieve_source, search_passages, locate_quote, ingest_pdf
    except ImportError as exc:
        logger.warning("[M4] citeverify_core.retrieval not available: %s", exc)
        return None, None, None, None


def _import_verify():
    try:
        from citeverify_core.verification import verify  # type: ignore
        return verify
    except ImportError as exc:
        logger.error("[M4] citeverify_core.verification not available: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Stub Source  (used when M2 is unavailable)
# ---------------------------------------------------------------------------

def _stub_source(ref: Reference) -> Source:
    """Return a placeholder Source so the pipeline can continue without M2."""
    return Source(
        reference_id=ref.reference_id,
        matched=False,
        match_score=0.0,
        title=ref.title or "",
        authors=ref.authors,
        year=ref.year,
        doi=ref.doi,
        url=None,
        pdf_path=None,
        text_level="none",
        full_text_available=False,
        source_database="unavailable",
        flags=["reference_not_found"],
    )


# ---------------------------------------------------------------------------
# Public pipeline entry points
# ---------------------------------------------------------------------------

def run_pipeline(
    file_path: Optional[str],
    raw_text: Optional[str],
    doc_id: str,
) -> tuple[ParsedDocument, dict[str, Source], list[Verdict]]:
    """
    Run the full verification pipeline for one document.

    Parameters
    ----------
    file_path:  Path to uploaded file, or None if pasting text.
    raw_text:   Pasted text, or None if uploading a file.
    doc_id:     Unique document identifier.

    Returns
    -------
    (parsed_doc, sources_by_ref_id, verdicts)
    """
    parse_document = _import_parse_document()
    retrieve_source, _, _, _ = _import_m2()
    verify = _import_verify()

    # ── 1. Parse ─────────────────────────────────────────────────────────────
    if parse_document is None:
        from citeverify_core.common.schemas import ParsedDocument
        logger.error("[M4] M1 unavailable; returning empty ParsedDocument.")
        return (
            ParsedDocument(doc_id=doc_id, source_type="text", warnings=["m1_unavailable"]),
            {},
            [],
        )

    parsed: ParsedDocument = parse_document(
        file_path=file_path,
        raw_text=raw_text,
        doc_id=doc_id,
    )
    logger.info(
        "[M4] Parsed doc=%s claims=%d refs=%d",
        doc_id, len(parsed.claims), len(parsed.references),
    )

    # ── 2. Retrieve sources ───────────────────────────────────────────────────
    sources: dict[str, Source] = {}
    for ref in parsed.references:
        if retrieve_source is not None:
            try:
                source = retrieve_source(ref)
            except Exception as exc:
                logger.warning(
                    "[M4] retrieve_source failed for ref %s: %s", ref.reference_id, exc
                )
                source = _stub_source(ref)
        else:
            source = _stub_source(ref)
        sources[ref.reference_id] = source

    # Build lookup maps
    ref_map: dict[str, Reference] = {r.reference_id: r for r in parsed.references}

    # ── 3. Verify ─────────────────────────────────────────────────────────────
    verdicts: list[Verdict] = []
    for claim in parsed.claims:
        for ref_id in claim.reference_ids:
            ref = ref_map.get(ref_id)
            source = sources.get(ref_id)
            if ref is None or source is None:
                logger.debug(
                    "[M4] Skipping (claim=%s, ref=%s): ref or source not found.",
                    claim.claim_id, ref_id,
                )
                continue

            if verify is not None:
                try:
                    verdict = verify(claim, ref, source)
                    verdicts.append(verdict)
                except Exception as exc:
                    logger.error(
                        "[M4] verify() raised for claim=%s ref=%s: %s",
                        claim.claim_id, ref_id, exc,
                    )
            else:
                logger.warning("[M4] M3 verify not available; skipping claim=%s", claim.claim_id)

    logger.info("[M4] Pipeline done: doc=%s verdicts=%d", doc_id, len(verdicts))
    return parsed, sources, verdicts


def run_reverify_for_reference(
    reference_id: str,
    all_claims: list[Claim],
    reference: Reference,
    source: Source,
) -> list[Verdict]:
    """
    Re-run verification for all claims that cite reference_id.
    Called after POST /api/references/{reference_id}/source.
    """
    verify = _import_verify()
    if verify is None:
        logger.error("[M4] Cannot reverify: M3 not available.")
        return []

    try:
        from citeverify_core.verification.engine import reverify_for_reference
        return reverify_for_reference(reference_id, all_claims, reference, source)
    except Exception as exc:
        logger.error("[M4] reverify_for_reference failed: %s", exc)
        return []
