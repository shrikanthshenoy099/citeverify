"""
citeverify_core/doc_intel/__init__.py

M1 – Document Intelligence module.
This stub allows the M4 orchestrator to import the package without crashing
before M1 delivers their implementation.

M1 team: replace this file with the real implementation on branch m1-doc-intel.
"""

from __future__ import annotations

from typing import Optional

from citeverify_core.common.schemas import ParsedDocument


def parse_document(
    file_path: Optional[str],
    raw_text: Optional[str],
    doc_id: str,
) -> ParsedDocument:
    """
    Parse an uploaded document and extract claims + references.

    Parameters
    ----------
    file_path : Path to the uploaded PDF or DOCX file (None for pasted text).
    raw_text  : Pasted plain text (None for file uploads).
    doc_id    : Unique document ID assigned by M4.

    Returns
    -------
    ParsedDocument with references, claims, and any warnings.

    Raises
    ------
    NotImplementedError – this stub; M1 will implement it.
    """
    raise NotImplementedError(
        "parse_document is not yet implemented. M1 team: implement this in doc_intel/."
    )
