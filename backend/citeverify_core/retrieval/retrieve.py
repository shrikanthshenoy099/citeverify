"""
M2 – retrieve_source: core orchestration logic.

Tries each data source in priority order, matches the result against the
Reference, downloads a PDF if available, extracts text and builds the index.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..common.schemas import Reference, Source
from .chunker import build_chunks
from .config import INDEX_DIR, LOW_RETRIEVAL_THRESHOLD, SOURCES_DIR
from .fetchers import (
    arxiv_normalize,
    arxiv_search_title,
    crossref_by_doi,
    crossref_normalize,
    crossref_search_title,
    openalex_normalize,
    openalex_search_title,
    s2_normalize,
    s2_search_title,
    unpaywall_by_doi,
    unpaywall_pdf_url,
)
from .indexer import build_index, index_exists
from .matcher import is_matched
from .pdf_handler import download_pdf, extract_pages

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _not_found_source(reference_id: str, flags: list[str] | None = None) -> Source:
    """Return a Source indicating the reference was not found."""
    return Source(
        reference_id=reference_id,
        matched=False,
        match_score=0.0,
        title="",
        authors=[],
        year=None,
        doi=None,
        url=None,
        pdf_path=None,
        text_level="none",
        full_text_available=False,
        source_database="none",
        flags=flags or ["reference_not_found"],
    )


def _build_source_from_meta(
    reference: Reference,
    meta: dict[str, Any],
    matched: bool,
    match_score: float,
) -> Source:
    return Source(
        reference_id=reference.reference_id,
        matched=matched,
        match_score=match_score,
        title=meta.get("title") or "",
        authors=meta.get("authors") or [],
        year=meta.get("year"),
        doi=meta.get("doi"),
        url=meta.get("url"),
        pdf_path=None,
        text_level="metadata_only",
        full_text_available=False,
        source_database=meta.get("source_database", "unknown"),
        flags=_initial_flags(reference, meta),
    )


def _initial_flags(reference: Reference, meta: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    if not meta.get("doi"):
        flags.append("doi_not_resolved")
    # Title mismatch check (fuzzy already passed, but we keep mild warning for borderline cases)
    # Author / year mismatch
    ref_year = reference.year
    cand_year = meta.get("year")
    if ref_year and cand_year and abs(ref_year - cand_year) > 1:
        flags.append("year_mismatch")
    return flags


# ---------------------------------------------------------------------------
# Main resolution chain
# ---------------------------------------------------------------------------

def retrieve_source(reference: Reference) -> Source:
    """Resolve *reference* to an external paper, download PDF and build index.

    Returns a fully populated :class:`Source`.  Never raises; failures are
    encoded in the Source flags.
    """
    ref_id = reference.reference_id

    # --- Fast path: index already built ---
    if index_exists(ref_id):
        logger.debug("Index already exists for %s; reloading source metadata.", ref_id)
        return _load_cached_source(ref_id, reference)

    meta: dict[str, Any] | None = None

    # 1. Crossref – DOI direct
    if reference.doi:
        work = crossref_by_doi(reference.doi)
        if work:
            meta = crossref_normalize(work)
            meta["_crossref_raw"] = work  # keep for retraction check

    # 2. Crossref – title search
    if meta is None and reference.title:
        work = crossref_search_title(reference.title)
        if work:
            meta = crossref_normalize(work)
            meta["_crossref_raw"] = work

    # 3. OpenAlex – title search
    if meta is None and reference.title:
        work = openalex_search_title(reference.title)
        if work:
            meta = openalex_normalize(work)

    # 4. arXiv – title search
    if meta is None and reference.title:
        raw = arxiv_search_title(reference.title)
        if raw:
            meta = arxiv_normalize(raw)

    # 5. Semantic Scholar – title search (or DOI)
    if meta is None:
        if reference.doi:
            work = s2_search_title(reference.doi)  # S2 also accepts DOI queries
        elif reference.title:
            work = s2_search_title(reference.title)
        else:
            work = None
        if work:
            meta = s2_normalize(work)

    if meta is None:
        logger.info("Reference not found in any database: %s", ref_id)
        return _not_found_source(ref_id)

    # --- Match check ---
    matched, match_score = is_matched(
        reference,
        meta.get("title", ""),
        meta.get("authors", []),
        meta.get("year"),
    )
    if not matched:
        logger.info("Title match failed for %s (score=%.2f)", ref_id, match_score)
        flags = ["title_mismatch", "reference_not_found"]
        source = _build_source_from_meta(reference, meta, matched=False, match_score=match_score)
        return source.model_copy(update={"flags": flags})

    source = _build_source_from_meta(reference, meta, matched=True, match_score=match_score)

    # --- Resolve open-access PDF URL ---
    pdf_url: str | None = meta.get("url")

    # Try Unpaywall if we have a DOI and no PDF URL yet
    doi = meta.get("doi") or reference.doi
    if not pdf_url and doi:
        uw = unpaywall_by_doi(doi)
        if uw:
            pdf_url = unpaywall_pdf_url(uw)

    # --- Download PDF and build index ---
    if pdf_url:
        source, text_level, pdf_path = _process_pdf(ref_id, pdf_url, source)
        source = source.model_copy(update={"text_level": text_level, "pdf_path": pdf_path, "full_text_available": text_level == "full_text"})
    else:
        # Try abstract from OpenAlex if available
        abstract = _try_get_abstract(meta)
        if abstract:
            source = _index_abstract(ref_id, abstract, source)
        else:
            source = source.model_copy(update={"flags": list(source.flags) + ["full_text_unavailable"]})

    # --- Stretch: retraction check ---
    try:
        from .retraction import check_retraction
        source = check_retraction(source)
    except Exception as exc:
        logger.debug("Retraction check skipped: %s", exc)

    return source


# ---------------------------------------------------------------------------
# PDF processing
# ---------------------------------------------------------------------------

def _process_pdf(
    ref_id: str,
    pdf_url: str,
    source: Source,
) -> tuple[Source, str, str | None]:
    """Download PDF, extract text, build index.  Returns (source, text_level, pdf_path)."""
    local_path = download_pdf(pdf_url, ref_id)
    if local_path is None:
        flags = list(source.flags) + ["full_text_unavailable"]
        return source.model_copy(update={"flags": flags}), "metadata_only", None

    pages = extract_pages(local_path, ref_id)
    has_text = any(p.text.strip() for p in pages)
    if not has_text:
        flags = list(source.flags) + ["full_text_unavailable"]
        return source.model_copy(update={"flags": flags}), "metadata_only", str(local_path)

    has_ocr = any(p.is_ocr for p in pages)
    flags = list(source.flags)
    if has_ocr:
        if "ocr_text" not in flags:
            flags.append("ocr_text")

    chunks = build_chunks(pages, ref_id)
    if chunks:
        build_index(chunks, ref_id)
        text_level = "full_text"
    else:
        text_level = "metadata_only"

    return source.model_copy(update={"flags": flags}), text_level, str(local_path)


# ---------------------------------------------------------------------------
# Abstract fallback
# ---------------------------------------------------------------------------

def _try_get_abstract(meta: dict[str, Any]) -> str:
    """Extract abstract text from OpenAlex raw record if present."""
    raw = meta.get("_raw") or {}
    # OpenAlex: abstract_inverted_index -> reconstruct
    inverted = raw.get("abstract_inverted_index")
    if inverted:
        try:
            words: dict[int, str] = {}
            for word, positions in inverted.items():
                for pos in positions:
                    words[pos] = word
            return " ".join(v for _, v in sorted(words.items()))
        except Exception:
            pass
    return ""


def _index_abstract(ref_id: str, abstract: str, source: Source) -> Source:
    """Build a minimal index from an abstract string."""
    from .chunker import Chunk
    from .indexer import build_index as _build_index

    if not abstract.strip():
        return source
    chunk = Chunk(
        chunk_id=f"{ref_id}_abstract_0",
        reference_id=ref_id,
        page_index=0,
        text=abstract,
        start_word=0,
        is_ocr=False,
        section="abstract",
    )
    _build_index([chunk], ref_id)
    flags = list(source.flags) + ["abstract_only"]
    return source.model_copy(update={
        "text_level": "abstract_only",
        "full_text_available": False,
        "flags": flags,
    })


# ---------------------------------------------------------------------------
# Cached source reload
# ---------------------------------------------------------------------------

def _load_cached_source(ref_id: str, reference: Reference) -> Source:
    """Return a Source from an existing index without re-fetching."""
    pdf_path: str | None = None
    candidate = SOURCES_DIR / f"{ref_id}.pdf"
    if candidate.exists():
        pdf_path = str(candidate)

    # Detect text_level from index metadata
    import json
    meta_path = INDEX_DIR / ref_id / "metadata.json"
    has_ocr = False
    text_level = "full_text"
    if meta_path.exists():
        meta_list = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta_list:
            has_ocr = any(m.get("is_ocr") for m in meta_list)
            if meta_list[0].get("section") == "abstract":
                text_level = "abstract_only"

    flags: list[str] = []
    if has_ocr:
        flags.append("ocr_text")

    return Source(
        reference_id=ref_id,
        matched=True,
        match_score=1.0,
        title=reference.title or "",
        authors=reference.authors,
        year=reference.year,
        doi=reference.doi,
        url=None,
        pdf_path=pdf_path,
        text_level=text_level,  # type: ignore[arg-type]
        full_text_available=(text_level == "full_text"),
        source_database="cached",
        flags=flags,
    )
