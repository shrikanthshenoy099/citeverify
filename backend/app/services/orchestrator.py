"""
backend/app/services/orchestrator.py – Pipeline orchestrator (M4).

Runs the full verification pipeline for one uploaded document:
  1. M1: parse_document  → ParsedDocument
  2. For each reference  → M2: retrieve_source  → Source
  3. For each claim+ref  → M3: verify           → Verdict
  4. Persist all results to the database.

The function run_pipeline() is called in a background thread by the
documents router so POST /api/documents returns immediately with a doc_id.

M1 and M2 are imported lazily with graceful stubs so the M4 code
stays runnable before those modules are merged.
"""

from __future__ import annotations

import logging
import traceback
import uuid
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.models import ClaimRecord, DocumentRecord, ReferenceRecord, VerdictRecord
from citeverify_core.common.schemas import (
    Claim,
    ParsedDocument,
    Reference,
    Source,
    Verdict,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy M1 / M2 import with stubs
# ---------------------------------------------------------------------------


def _parse_document(
    file_path: Optional[str], raw_text: Optional[str], doc_id: str
) -> ParsedDocument:
    """Wrapper around M1.parse_document with a stub fallback."""
    try:
        from citeverify_core.doc_intel import parse_document  # type: ignore

        return parse_document(file_path=file_path, raw_text=raw_text, doc_id=doc_id)
    except ImportError:
        logger.warning("M1 doc_intel not available; returning stub ParsedDocument.")
        source_type = "text" if raw_text else "pdf"
        return ParsedDocument(
            doc_id=doc_id,
            source_type=source_type,  # type: ignore[arg-type]
            num_pages=None,
            references=[],
            claims=[],
            warnings=["M1 not integrated yet; no claims or references extracted."],
        )


def _retrieve_source(reference: Reference) -> Source:
    """Wrapper around M2.retrieve_source with a stub fallback."""
    try:
        from citeverify_core.retrieval import retrieve_source  # type: ignore

        return retrieve_source(reference)
    except ImportError:
        logger.warning("M2 retrieval not available; returning stub Source.")
        return Source(
            reference_id=reference.reference_id,
            matched=False,
            match_score=0.0,
            title=reference.title or "",
            authors=reference.authors,
            year=reference.year,
            doi=reference.doi,
            text_level="none",
            full_text_available=False,
            source_database="stub",
            flags=["reference_not_found"],
        )


def _ingest_pdf(reference_id: str, pdf_path: str) -> Source:
    """Wrapper around M2.ingest_pdf with a stub fallback."""
    try:
        from citeverify_core.retrieval import ingest_pdf  # type: ignore

        return ingest_pdf(reference_id, pdf_path)
    except ImportError:
        logger.warning("M2 ingest_pdf not available; returning stub Source.")
        return Source(
            reference_id=reference_id,
            matched=True,
            match_score=1.0,
            title="",
            text_level="full_text",
            full_text_available=True,
            source_database="manual",
            flags=["manual_source"],
        )


# ---------------------------------------------------------------------------
# DB persistence helpers
# ---------------------------------------------------------------------------


def _upsert_reference(db: Session, ref: Reference, doc_id: str, source: Source) -> None:
    existing = db.get(ReferenceRecord, ref.reference_id)
    if existing is None:
        existing = ReferenceRecord(reference_id=ref.reference_id, doc_id=doc_id)
        db.add(existing)

    existing.raw_text = ref.raw_text
    existing.title = ref.title
    existing.authors = ref.authors
    existing.year = ref.year
    existing.doi = ref.doi
    existing.venue = ref.venue
    existing.parse_confidence = ref.parse_confidence
    existing.matched = source.matched
    existing.source_title = source.title
    existing.source_url = source.url
    existing.source_pdf_path = source.pdf_path
    existing.text_level = source.text_level
    existing.source_flags = source.flags
    existing.source_json = source.model_dump()


def _upsert_claim(db: Session, claim: Claim, doc_id: str) -> None:
    existing = db.get(ClaimRecord, claim.claim_id)
    if existing is None:
        existing = ClaimRecord(claim_id=claim.claim_id, doc_id=doc_id)
        db.add(existing)

    existing.text = claim.text
    existing.page = claim.page
    existing.section = claim.section
    existing.char_start = claim.char_start
    existing.char_end = claim.char_end
    existing.claim_type = claim.claim_type
    existing.citation_markers = claim.citation_markers
    existing.reference_ids = claim.reference_ids
    existing.numbers_mentioned = claim.numbers_mentioned
    existing.context_before = claim.context_before
    existing.context_after = claim.context_after
    existing.flags = claim.flags


def _upsert_verdict(db: Session, verdict: Verdict) -> None:
    # Delete previous verdict for this (claim, reference) pair before inserting new one
    from sqlalchemy import delete
    db.execute(
        delete(VerdictRecord).where(
            VerdictRecord.claim_id == verdict.claim_id,
            VerdictRecord.reference_id == verdict.reference_id,
        )
    )
    record = VerdictRecord(
        claim_id=verdict.claim_id,
        reference_id=verdict.reference_id,
        verdict=verdict.verdict,
        explanation=verdict.explanation,
        confidence=verdict.confidence,
        needs_human_review=verdict.needs_human_review,
        flags=verdict.flags,
        verdict_json=verdict.model_dump(),
    )
    db.add(record)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def run_pipeline(
    doc_id: str,
    file_path: Optional[str],
    raw_text: Optional[str],
    db_session_factory,
) -> None:
    """
    Execute the full parse → retrieve → verify pipeline for one document.

    Parameters
    ----------
    doc_id:              The document ID already created in the DB.
    file_path:           Path to the uploaded file (None for pasted text).
    raw_text:            Pasted text (None for file uploads).
    db_session_factory:  Callable returning a new SQLAlchemy Session.

    This function is designed to run in a thread (via BackgroundTasks).
    It catches all exceptions and writes them to DocumentRecord.error_message.
    """
    db: Session = db_session_factory()
    try:
        # Mark in-progress
        doc_rec = db.get(DocumentRecord, doc_id)
        if doc_rec is None:
            logger.error("run_pipeline: DocumentRecord %s not found.", doc_id)
            return
        doc_rec.status = "processing"
        db.commit()

        # ── Step 1: Parse ────────────────────────────────────────────────────
        logger.info("[pipeline] %s: parsing document.", doc_id)
        parsed: ParsedDocument = _parse_document(file_path, raw_text, doc_id)

        doc_rec.num_pages = parsed.num_pages
        doc_rec.warnings = parsed.warnings
        db.commit()

        # Persist references and claims
        ref_map: dict[str, Reference] = {}
        for ref in parsed.references:
            ref_map[ref.reference_id] = ref

        claim_map: dict[str, Claim] = {}
        for claim in parsed.claims:
            _upsert_claim(db, claim, doc_id)
            claim_map[claim.claim_id] = claim
        db.commit()

        # ── Step 2: Retrieve sources ─────────────────────────────────────────
        logger.info("[pipeline] %s: retrieving %d sources.", doc_id, len(parsed.references))
        source_map: dict[str, Source] = {}
        for ref in parsed.references:
            try:
                source = _retrieve_source(ref)
            except Exception as exc:  # noqa: BLE001
                logger.warning("retrieve_source failed for %s: %s", ref.reference_id, exc)
                source = Source(
                    reference_id=ref.reference_id,
                    matched=False,
                    match_score=0.0,
                    title=ref.title or "",
                    text_level="none",
                    full_text_available=False,
                    source_database="error",
                    flags=["reference_not_found"],
                )
            source_map[ref.reference_id] = source
            _upsert_reference(db, ref, doc_id, source)
        db.commit()

        # ── Step 3: Verify (one Verdict per claim×reference pair) ────────────
        from citeverify_core.verification import verify

        total_pairs = sum(len(c.reference_ids) for c in parsed.claims)
        logger.info("[pipeline] %s: verifying %d (claim, ref) pairs.", doc_id, total_pairs)

        for claim in parsed.claims:
            for ref_id in claim.reference_ids:
                ref = ref_map.get(ref_id)
                source = source_map.get(ref_id)
                if ref is None or source is None:
                    logger.warning(
                        "No ref/source for ref_id=%s in claim=%s; skipping.",
                        ref_id, claim.claim_id,
                    )
                    continue
                try:
                    verdict = verify(claim, ref, source)
                    _upsert_verdict(db, verdict)
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "verify() failed for claim=%s ref=%s: %s",
                        claim.claim_id, ref_id, exc,
                    )
            db.commit()

        # ── Done ─────────────────────────────────────────────────────────────
        doc_rec.status = "done"
        db.commit()
        logger.info("[pipeline] %s: complete.", doc_id)

    except Exception as exc:  # noqa: BLE001
        logger.error("[pipeline] %s: fatal error: %s", doc_id, traceback.format_exc())
        try:
            doc_rec = db.get(DocumentRecord, doc_id)
            if doc_rec:
                doc_rec.status = "error"
                doc_rec.error_message = str(exc)
                db.commit()
        except Exception:  # noqa: BLE001
            pass
    finally:
        db.close()
