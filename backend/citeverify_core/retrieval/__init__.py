"""
M2 – Source Retrieval public interface.

Exported functions (synchronous):
    retrieve_source(reference)              -> Source
    search_passages(reference_id, query, k) -> list[Passage]
    locate_quote(reference_id, quote)       -> Evidence | None
    ingest_pdf(reference_id, pdf_path)      -> Source   # reviewer-supplied PDF
"""
from __future__ import annotations

import logging

from ..common.schemas import Evidence, Passage, Reference, Source
from .ingest import ingest_pdf as _ingest_pdf
from .passage_search import locate_quote as _locate_quote
from .passage_search import search_passages as _search_passages
from .retrieve import retrieve_source as _retrieve_source

logger = logging.getLogger(__name__)

__all__ = [
    "retrieve_source",
    "search_passages",
    "locate_quote",
    "ingest_pdf",
]


def retrieve_source(reference: Reference) -> Source:
    """Locate, download and index the paper identified by *reference*.

    Resolution order:
      1. Crossref (DOI resolve / title search)
      2. OpenAlex (title search)
      3. arXiv (title search)
      4. Unpaywall (DOI -> open-access PDF)
      5. Semantic Scholar (optional)

    Returns a :class:`~citeverify_core.common.schemas.Source` with
    ``matched=True`` when the paper is found and ``matched=False`` otherwise.
    Always returns a Source (never raises).
    """
    return _retrieve_source(reference)


def search_passages(reference_id: str, query: str, k: int = 5) -> list[Passage]:
    """Return up to *k* relevant :class:`~...schemas.Passage` objects for *query*.

    Returns an empty list when the index is not built or the reference is unknown.
    """
    return _search_passages(reference_id, query, k=k)


def locate_quote(reference_id: str, quote: str) -> Evidence | None:
    """Find *quote* in the indexed source text using fuzzy matching.

    Returns :class:`~...schemas.Evidence` with page and bboxes when found,
    or ``None`` when the quote cannot be located above the confidence threshold.
    """
    return _locate_quote(reference_id, quote)


def ingest_pdf(reference_id: str, pdf_path: str) -> Source:
    """Build a Source + embedding index from a reviewer-supplied PDF.

    Sets ``manual_source`` flag; OCR pages additionally get ``ocr_text`` flag.
    Overwrites any previous index for *reference_id*.
    """
    return _ingest_pdf(reference_id, pdf_path)
