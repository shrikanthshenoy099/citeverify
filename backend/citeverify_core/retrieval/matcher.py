"""
M2 – Title / author / year matching logic.

Given a Reference and a normalised metadata dict (from fetchers.py), decide
whether the external record is the same paper.

Decision rules (from Decisions Addendum):
  matched = (title_ratio >= TITLE_RATIO_MATCHED)
              AND (first_author_surname_matches OR year_within_tolerance)
  OR
  title_ratio >= TITLE_RATIO_SOLO  (even if author/year are absent)
"""
from __future__ import annotations

import logging
import re

from rapidfuzz import fuzz

from ..common.schemas import Reference
from .config import (
    TITLE_RATIO_MATCHED,
    TITLE_RATIO_SOLO,
    YEAR_TOLERANCE,
)

logger = logging.getLogger(__name__)


def _normalise_title(t: str) -> str:
    """Lower-case and strip punctuation for robust comparison."""
    t = t.lower()
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _first_surname(authors: list[str]) -> str:
    """Return the lower-cased surname of the first author."""
    if not authors:
        return ""
    name = authors[0]
    # Handle "LastName, First" and "First LastName" conventions
    if "," in name:
        return name.split(",")[0].strip().lower()
    parts = name.split()
    return parts[-1].lower() if parts else ""


def title_ratio(ref_title: str, cand_title: str) -> float:
    """Return a composite title similarity score (0-100).

    Uses ``token_set_ratio`` for vocabulary overlap, but penalises extreme
    length mismatches so that a 2-word title cannot absorb a 10-word title.

    Length-penalty rule: if the shorter title is fewer than 40% of the
    longer title's word count, the raw ``token_set_ratio`` is multiplied
    by  (short_wc / (0.4 * long_wc)) so the final score is capped below
    the threshold.  This prevents "About Unicorns" matching
    "Completely Nonexistent Paper About Invisible Unicorns 2099 XYZZY".
    """
    n_ref = _normalise_title(ref_title)
    n_cand = _normalise_title(cand_title)
    raw = fuzz.token_set_ratio(n_ref, n_cand)

    # Length-mismatch penalty
    ref_wc = len(n_ref.split())
    cand_wc = len(n_cand.split())
    if ref_wc > 0 and cand_wc > 0:
        shorter = min(ref_wc, cand_wc)
        longer = max(ref_wc, cand_wc)
        length_ratio = shorter / longer  # 0..1
        MIN_LENGTH_RATIO = 0.40
        if length_ratio < MIN_LENGTH_RATIO:
            # scale raw score down proportionally
            penalty = length_ratio / MIN_LENGTH_RATIO  # 0..1
            raw = raw * penalty

    return raw


def year_matches(ref_year: int | None, cand_year: int | None) -> bool:
    """Return True if years are within YEAR_TOLERANCE of each other."""
    if ref_year is None or cand_year is None:
        return False
    return abs(ref_year - cand_year) <= YEAR_TOLERANCE


def author_matches(ref_authors: list[str], cand_authors: list[str]) -> bool:
    """Return True if first-author surnames are equal (case-insensitive)."""
    if not ref_authors or not cand_authors:
        return False
    return _first_surname(ref_authors) == _first_surname(cand_authors)


def compute_match_score(ratio: float) -> float:
    """Normalise a rapidfuzz 0-100 ratio to a 0-1 score."""
    return round(ratio / 100.0, 4)


def is_matched(
    reference: Reference,
    cand_title: str,
    cand_authors: list[str],
    cand_year: int | None,
) -> tuple[bool, float]:
    """Return (matched: bool, match_score: float 0-1).

    Parameters
    ----------
    reference:
        The input Reference from the parsed document.
    cand_title, cand_authors, cand_year:
        Fields from the external metadata record.
    """
    ref_title = reference.title or ""
    if not ref_title or not cand_title:
        return False, 0.0

    ratio = title_ratio(ref_title, cand_title)
    score = compute_match_score(ratio)

    if ratio >= TITLE_RATIO_SOLO:
        logger.debug(
            "Title-only match (ratio=%.1f >= %.1f): '%s'",
            ratio,
            TITLE_RATIO_SOLO,
            cand_title[:80],
        )
        return True, score

    if ratio >= TITLE_RATIO_MATCHED:
        ref_auth = reference.authors
        ref_year = reference.year
        auth_ok = author_matches(ref_auth, cand_authors)
        year_ok = year_matches(ref_year, cand_year)
        if auth_ok or year_ok:
            logger.debug(
                "Title+author/year match (ratio=%.1f): '%s'",
                ratio,
                cand_title[:80],
            )
            return True, score

    return False, score
