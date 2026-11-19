"""
verification/verdict.py – LLM prompt construction and verdict determination.

Prompts are loaded from verification/prompts/*.txt so they can be edited
without touching Python code.
"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import Optional

from citeverify_core.common.schemas import (
    Claim,
    Reference,
    Source,
    VerdictLabel,
)
from citeverify_core.verification import config

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(filename: str) -> str:
    """Load a prompt template from the prompts/ directory."""
    path = _PROMPTS_DIR / filename
    return path.read_text(encoding="utf-8").rstrip()


# Cache prompts at module load time
_SYSTEM_PROMPT: str = _load_prompt("system.txt")
_USER_TEMPLATE: str = _load_prompt("user.txt")

# ---------------------------------------------------------------------------
# JSON Schema for LLM response
# ---------------------------------------------------------------------------

LLM_RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "verdict": {
            "type": "string",
            "enum": [
                "supported",
                "partly_supported",
                "unsupported",
                "contradictory",
                "possibly_outdated",
                "needs_review",
            ],
        },
        "explanation": {"type": "string"},
        "llm_certainty": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "supporting_quote": {"type": ["string", "null"]},
        "time_sensitive": {"type": "boolean"},
        "numbers_match": {"type": "boolean"},
        "scope_mismatch": {"type": "boolean"},
    },
    "required": [
        "verdict", "explanation", "llm_certainty",
        "time_sensitive", "numbers_match", "scope_mismatch",
    ],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def build_prompts(
    claim: Claim,
    reference: Reference,
    source: Source,
    passages: list[str],
) -> tuple[str, str]:
    """
    Return (system_prompt, user_prompt) for the LLM.
    Both are loaded from verification/prompts/*.txt.
    """
    passage_block = "\n\n---\n\n".join(passages) if passages else "(No text retrieved)"
    numbers = ", ".join(claim.numbers_mentioned) if claim.numbers_mentioned else "none"

    user = _USER_TEMPLATE.format(
        claim_text=claim.text,
        claim_type=claim.claim_type,
        numbers=numbers,
        source_title=source.title or reference.title or "unknown",
        source_authors=", ".join(source.authors or reference.authors) or "unknown",
        source_year=source.year or reference.year or "unknown",
        source_doi=source.doi or reference.doi or "N/A",
        source_passages=passage_block,
    )
    return _SYSTEM_PROMPT, user


# ---------------------------------------------------------------------------
# Possibly-outdated override
# ---------------------------------------------------------------------------

def maybe_override_possibly_outdated(
    verdict: VerdictLabel,
    source_year: Optional[int],
    time_sensitive: bool,
) -> VerdictLabel:
    """
    Override verdict to 'possibly_outdated' when source is older than
    POSSIBLY_OUTDATED_YEARS AND the LLM says the claim is time-sensitive.
    Does NOT override 'contradictory'.
    """
    if verdict == "contradictory":
        return verdict
    if not time_sensitive or source_year is None:
        return verdict
    current_year = datetime.datetime.now(datetime.timezone.utc).year
    age = current_year - source_year
    if age > config.POSSIBLY_OUTDATED_YEARS:
        logger.debug(
            "Overriding verdict %r → 'possibly_outdated' (source year %d, age %d).",
            verdict, source_year, age,
        )
        return "possibly_outdated"
    return verdict


# ---------------------------------------------------------------------------
# LLM response → typed result
# ---------------------------------------------------------------------------

def parse_llm_response(llm_data: dict) -> tuple[
    VerdictLabel,
    str,
    float,
    Optional[str],
    bool,
    bool,
    bool,
]:
    """
    Extract typed fields from a validated LLM response dict.

    Returns
    -------
    (verdict, explanation, llm_certainty, supporting_quote,
     time_sensitive, numbers_match, scope_mismatch)
    """
    verdict: VerdictLabel = llm_data["verdict"]  # type: ignore[assignment]
    explanation: str = llm_data["explanation"]
    llm_certainty: float = float(llm_data["llm_certainty"])
    supporting_quote: Optional[str] = llm_data.get("supporting_quote")
    time_sensitive: bool = bool(llm_data["time_sensitive"])
    numbers_match: bool = bool(llm_data["numbers_match"])
    scope_mismatch: bool = bool(llm_data.get("scope_mismatch", False))
    return (
        verdict, explanation, llm_certainty, supporting_quote,
        time_sensitive, numbers_match, scope_mismatch,
    )
