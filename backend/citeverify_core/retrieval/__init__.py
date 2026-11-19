"""
citeverify_core/retrieval/__init__.py

M2 – Source Retrieval module.
This stub allows the M4 orchestrator and M3 engine to import the package
without crashing before M2 delivers their implementation.

M2 team: replace this file with the real implementation on branch m2-retrieval.
"""

from __future__ import annotations

from typing import Optional

from citeverify_core.common.schemas import Evidence, Passage, Reference, Source


def retrieve_source(reference: Reference) -> Source:
    """
    Retrieve bibliographic metadata and full text for a reference.

    Returns
    -------
    Source with matched=True and text if found, or matched=False otherwise.

    Raises
    ------
    NotImplementedError – this stub; M2 will implement it.
    """
    raise NotImplementedError(
        "retrieve_source is not yet implemented. M2 team: implement this in retrieval/."
    )


def search_passages(reference_id: str, query: str, k: int = 5) -> list[Passage]:
    """
    Return the top-k passages most relevant to *query* from the indexed source.

    Raises
    ------
    NotImplementedError – this stub; M2 will implement it.
    """
    raise NotImplementedError(
        "search_passages is not yet implemented. M2 team: implement this in retrieval/."
    )


def locate_quote(reference_id: str, quote: str) -> Optional[Evidence]:
    """
    Fuzzy-locate *quote* in the indexed source and return page + bboxes.

    Returns None if the quote cannot be found above the threshold.

    Raises
    ------
    NotImplementedError – this stub; M2 will implement it.
    """
    raise NotImplementedError(
        "locate_quote is not yet implemented. M2 team: implement this in retrieval/."
    )


def ingest_pdf(reference_id: str, pdf_path: str) -> Source:
    """
    Build a Source + search index from a manually uploaded PDF.

    Sets the manual_source flag and text_level="full_text".

    Raises
    ------
    NotImplementedError – this stub; M2 will implement it.
    """
    raise NotImplementedError(
        "ingest_pdf is not yet implemented. M2 team: implement this in retrieval/."
    )
