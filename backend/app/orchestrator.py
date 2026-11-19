"""
app/orchestrator.py – Pipeline orchestrator (M4).

Runs the full CiteVerify pipeline for a document:
  1. Parse (M1)
  2. Retrieve sources (M2) – per reference, failures isolated
  3. Verify claims (M3)   – per (claim, reference) pair, failures isolated
  4. Persist results to DB

Resilience contract:
- A single failing item (retrieval, verify) never aborts the whole run.
- Claims with no citation markers get a synthetic ``no_citation`` verdict.
- When USE_MOCKS=false and a module raises NotImplementedError or ImportError,
  the item is marked ``needs_review`` with flag ``llm_output_invalid``; the run
  continues and completes with status="done".
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import ClaimRow, DocumentRow, ReferenceRow, SourceRow, VerdictRow
from citeverify_core.common.schemas import (
    Claim,
    ConfidenceBreakdown,
    Flags,
    ParsedDocument,
    Reference,
    Source,
    SourceTrace,
    Verdict,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module imports with graceful mock fallbacks
# ---------------------------------------------------------------------------

def _import_parse_document():
    if settings.use_mocks:
        from app.mocks import mock_parse_document as fn
        return fn
    from citeverify_core.doc_intel.parser import parse_document as fn
    return fn


def _import_retrieve_source():
    if settings.use_mocks:
        from app.mocks import mock_retrieve_source as fn
        return fn
    from citeverify_core.retrieval import retrieve_source as fn
    return fn


def _import_verify():
    if settings.use_mocks:
        from app.mocks import mock_verify as fn
        return fn
    from citeverify_core.verification.engine import verify as fn
    return fn

# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    doc_id: str,
    db: Session,
    file_path: Optional[str] = None,
    raw_text: Optional[str] = None,
) -> None:
    """
    Execute the full pipeline for *doc_id*.  Called from a background thread.

    Updates ``DocumentRow.status`` at each stage.  On unrecoverable error
    (parse failure only), sets status = "error". All other failures are
    isolated per-item and logged; the run always reaches status="done".
    """
    _set_status(db, doc_id, "parsing")
    try:
        parse_document = _import_parse_document()
        parsed: ParsedDocument = parse_document(
            file_path=file_path,
            raw_text=raw_text,
            doc_id=doc_id,
        )
    except Exception as exc:
        logger.exception("Pipeline parse failed for doc_id=%s", doc_id)
        _set_status(db, doc_id, "error", str(exc))
        return

    # Persist claims and references
    _persist_parsed(db, parsed)

    # --- Synthetic no_citation verdicts ---
    # Claims with no reference_ids get a verdict immediately without retrieval.
    for claim in parsed.claims:
        if not claim.reference_ids:
            verdict = _make_no_citation_verdict(claim)
            _upsert_verdict(db, verdict)

    _set_status(db, doc_id, "retrieving")
    sources: dict[str, Source] = {}
    retrieve_source = _import_retrieve_source()
    for ref in parsed.references:
        try:
            source = retrieve_source(ref)
            sources[ref.reference_id] = source
            _upsert_source(db, source)
        except Exception as exc:
            logger.warning("Retrieval failed for reference %s: %s", ref.reference_id, exc)
            # Store a failed stub so verify step still runs with something
            stub = _make_failed_source(ref)
            sources[ref.reference_id] = stub
            _upsert_source(db, stub)

    _set_status(db, doc_id, "verifying")
    verify = _import_verify()
    ref_map: dict[str, Reference] = {r.reference_id: r for r in parsed.references}

    for claim in parsed.claims:
        if not claim.reference_ids:
            continue  # already handled above
        for ref_id in claim.reference_ids:
            ref = ref_map.get(ref_id)
            source = sources.get(ref_id)
            if ref is None:
                logger.warning("Claim %s references unknown ref %s", claim.claim_id, ref_id)
                continue
            if source is None:
                source = _make_failed_source(ref)
            try:
                verdict: Verdict = verify(claim, ref, source)
                _upsert_verdict(db, verdict)
            except Exception as exc:
                logger.warning(
                    "Verify failed claim=%s ref=%s: %s", claim.claim_id, ref_id, exc
                )
                # Persist a needs_review sentinel so the UI always has a row
                _upsert_verdict(db, _make_error_verdict(claim, ref, str(exc)))

    _set_status(db, doc_id, "done")
    logger.info("Pipeline complete for doc_id=%s", doc_id)


# ---------------------------------------------------------------------------
# Re-verify a single reference (after manual source upload)
# ---------------------------------------------------------------------------

def reverify_reference(reference_id: str, db: Session) -> None:
    """
    Re-run verify() for every claim that cites *reference_id*.
    Called after M2.ingest_pdf() updates the source.
    """
    source_row = db.get(SourceRow, reference_id)
    ref_row = db.get(ReferenceRow, reference_id)
    if source_row is None or ref_row is None:
        logger.warning("reverify_reference: missing rows for reference_id=%s", reference_id)
        return

    source = Source(**json.loads(source_row.payload))
    ref = Reference(**json.loads(ref_row.payload))

    # Find all claims that reference this ref_id
    verify = _import_verify()
    claim_rows = (
        db.query(ClaimRow)
        .filter(ClaimRow.doc_id == ref_row.doc_id)
        .all()
    )
    for cr in claim_rows:
        claim = Claim(**json.loads(cr.payload))
        if reference_id not in claim.reference_ids:
            continue
        try:
            verdict = verify(claim, ref, source)
            _upsert_verdict(db, verdict)
        except Exception as exc:
            logger.warning("reverify failed claim=%s ref=%s: %s", claim.claim_id, reference_id, exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_status(db: Session, doc_id: str, status: str, error: Optional[str] = None) -> None:
    row = db.get(DocumentRow, doc_id)
    if row:
        row.status = status
        row.error_message = error
        db.commit()


def _persist_parsed(db: Session, parsed: ParsedDocument) -> None:
    for ref in parsed.references:
        existing = db.get(ReferenceRow, ref.reference_id)
        if existing is None:
            db.add(ReferenceRow(
                reference_id=ref.reference_id,
                doc_id=parsed.doc_id,
                payload=ref.model_dump_json(),
            ))
        else:
            existing.payload = ref.model_dump_json()

    for claim in parsed.claims:
        existing = db.get(ClaimRow, claim.claim_id)
        if existing is None:
            db.add(ClaimRow(
                claim_id=claim.claim_id,
                doc_id=parsed.doc_id,
                payload=claim.model_dump_json(),
            ))
        else:
            existing.payload = claim.model_dump_json()
    db.commit()


def _upsert_source(db: Session, source: Source) -> None:
    existing = db.get(SourceRow, source.reference_id)
    if existing is None:
        db.add(SourceRow(reference_id=source.reference_id, payload=source.model_dump_json()))
    else:
        existing.payload = source.model_dump_json()
    db.commit()


def _upsert_verdict(db: Session, verdict: Verdict) -> None:
    existing = (
        db.query(VerdictRow)
        .filter(
            VerdictRow.claim_id == verdict.claim_id,
            VerdictRow.reference_id == verdict.reference_id,
        )
        .first()
    )
    if existing is None:
        db.add(VerdictRow(
            claim_id=verdict.claim_id,
            reference_id=verdict.reference_id,
            payload=verdict.model_dump_json(),
        ))
    else:
        existing.payload = verdict.model_dump_json()
    db.commit()


def _make_no_citation_verdict(claim: Claim) -> Verdict:
    """Return a synthetic Verdict for a claim that has no reference_ids."""
    return Verdict(
        claim_id=claim.claim_id,
        reference_id="__no_citation__",
        verdict="needs_review",
        explanation="This claim has no citation. It cannot be verified against a source.",
        evidence=None,
        confidence=0.0,
        confidence_breakdown=ConfidenceBreakdown(
            retrieval=0.0,
            llm_certainty=0.0,
            text_match=0.0,
            full_text=0.0,
            numeric_match=0.0,
        ),
        source_trace=SourceTrace(doi=None, url=None, page=None, section=None),
        flags=[Flags.NO_CITATION],
        needs_human_review=True,
    )


def _make_failed_source(ref: Reference) -> Source:
    """Return a stub Source when retrieval fails, so verify can still run."""
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
        source_database="",
        flags=[Flags.REFERENCE_NOT_FOUND, Flags.FULL_TEXT_UNAVAILABLE],
    )


def _make_error_verdict(claim: Claim, ref: Reference, error_msg: str) -> Verdict:
    """Return a needs_review sentinel Verdict when verify() raises."""
    return Verdict(
        claim_id=claim.claim_id,
        reference_id=ref.reference_id,
        verdict="needs_review",
        explanation=f"Verification failed due to an internal error. Human review required. ({error_msg[:200]})",
        evidence=None,
        confidence=0.0,
        confidence_breakdown=ConfidenceBreakdown(
            retrieval=0.0,
            llm_certainty=0.0,
            text_match=0.0,
            full_text=0.0,
            numeric_match=0.0,
        ),
        source_trace=SourceTrace(
            doi=ref.doi,
            url=None,
            page=None,
            section=None,
        ),
        flags=[Flags.LLM_OUTPUT_INVALID],
        needs_human_review=True,
    )
