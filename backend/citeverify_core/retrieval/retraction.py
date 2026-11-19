"""
M2 – Stretch feature: retraction check via Crossref.

Inspects the ``relation`` and ``update-to`` fields of a Crossref work record
for retraction notices.  If a retraction is found, adds flag "possibly_retracted".

This is a STRETCH feature; it is called only after the main pipeline succeeds.
Silently returns the unmodified source if Crossref is unavailable or the field
is absent.
"""
from __future__ import annotations

import logging
from typing import Any

from ..common.schemas import Source
from .fetchers import crossref_by_doi

logger = logging.getLogger(__name__)

# Crossref update types that indicate retraction
_RETRACTION_TYPES = {
    "retraction",
    "retraction_of",
    "is-retracted-by",
}


def check_retraction(source: Source) -> Source:
    """Return *source*, adding "possibly_retracted" flag if Crossref indicates retraction.

    Parameters
    ----------
    source:
        The Source object as returned by retrieve_source().  Must have a DOI
        to perform the check; otherwise returns unchanged.
    """
    if not source.doi:
        return source

    work = crossref_by_doi(source.doi)
    if work is None:
        return source

    if _is_retracted(work):
        logger.info("possibly_retracted flag added for DOI %s", source.doi)
        flags = list(source.flags)
        if "possibly_retracted" not in flags:
            flags.append("possibly_retracted")
        return source.model_copy(update={"flags": flags})

    return source


def _is_retracted(work: dict[str, Any]) -> bool:
    """Return True if the Crossref work record indicates a retraction."""
    # Check update-to list (array of {type, DOI, label, updated})
    # The 'type' value for retractions is 'retraction' in Crossref JSON.
    for update in work.get("update-to", []) or []:
        update_type = (update.get("type") or "").lower().replace(" ", "_")
        if update_type in _RETRACTION_TYPES:
            return True

    # Also check relation field (newer Crossref schema)
    relation = work.get("relation") or {}
    for rel_type, rel_list in relation.items():
        if rel_type.lower() in _RETRACTION_TYPES:
            if rel_list:  # non-empty list means there is a retraction DOI
                return True

    return False
