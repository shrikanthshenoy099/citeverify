"""
verification/verdict.py – LLM prompt construction and verdict determination.

This module is responsible for:
  1. Building the system + user prompts sent to the LLM.
  2. Defining the JSON schema the LLM must return.
  3. Post-processing the LLM response into a typed VerdictLabel.
  4. Applying the possibly_outdated override rule.
"""

from __future__ import annotations

import datetime
import logging
from typing import Optional

from citeverify_core.common.schemas import (
    Claim,
    Reference,
    Source,
    VerdictLabel,
)
from citeverify_core.verification import config

logger = logging.getLogger(__name__)

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
    },
    "required": ["verdict", "explanation", "llm_certainty", "time_sensitive", "numbers_match"],
    "additionalProperties": False,
}

# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a scientific fact-checker assisting human reviewers. Your role is to evaluate whether a \
specific claim from an academic document is supported by the provided source text.

You MUST respond ONLY with a valid JSON object matching the required schema. Do NOT add any \
surrounding text, markdown, or commentary.

Verdict options (choose the most appropriate):
  supported           – The source text clearly and directly supports the claim.
  partly_supported    – The source partially supports the claim but with caveats or missing aspects.
  unsupported         – The source does not provide evidence for the claim.
  contradictory       – The source contradicts the claim.
  possibly_outdated   – The source is old and the evidence may no longer reflect current knowledge.
  needs_review        – Insufficient information to make a determination; human review required.

Be conservative: when in doubt, choose needs_review rather than a confident wrong verdict.
Your output assists human reviewers and must NEVER be presented as a final academic judgment."""

_USER_PROMPT_TEMPLATE = """\
## Claim to verify
{claim_text}

## Claim type
{claim_type}

## Numbers mentioned in the claim
{numbers}

## Source metadata
- Title  : {source_title}
- Authors: {source_authors}
- Year   : {source_year}
- DOI    : {source_doi}

## Source evidence (passage retrieved from the paper)
{source_passages}

## Task
1. Determine whether the source evidence supports the claim above.
2. Identify whether the claim involves time-sensitive information (e.g. rates, rankings, \
   current state-of-the-art).
3. Check whether specific numbers/statistics in the claim are present in the source.

Respond with a JSON object with these fields:
- verdict       (string enum)
- explanation   (string, 1–3 sentences, evidence-based)
- llm_certainty (float 0–1, your confidence in the verdict)
- supporting_quote (string | null, verbatim quote from the source, or null if none found)
- time_sensitive (bool)
- numbers_match (bool)"""


def build_prompts(
    claim: Claim,
    reference: Reference,
    source: Source,
    passages: list[str],
) -> tuple[str, str]:
    """
    Return (system_prompt, user_prompt) for the LLM.

    Parameters
    ----------
    claim:     The claim being verified.
    reference: The reference attached to the claim.
    source:    The retrieved Source for the reference.
    passages:  List of relevant passage texts (top-k from M2).
    """
    passage_block = "\n\n---\n\n".join(passages) if passages else "(No text retrieved)"

    numbers = ", ".join(claim.numbers_mentioned) if claim.numbers_mentioned else "none"

    user = _USER_PROMPT_TEMPLATE.format(
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
    Override verdict to 'possibly_outdated' if the source is older than
    POSSIBLY_OUTDATED_YEARS AND the LLM says the claim is time-sensitive.

    This rule is applied regardless of what verdict the LLM chose, to catch
    cases where the LLM correctly identified support but the evidence may be stale.
    Does NOT override 'contradictory' — a contradiction is still a contradiction.
    """
    if verdict == "contradictory":
        return verdict

    if not time_sensitive:
        return verdict

    if source_year is None:
        return verdict

    current_year = datetime.datetime.now(datetime.timezone.utc).year
    age = current_year - source_year
    if age > config.POSSIBLY_OUTDATED_YEARS:
        logger.debug(
            "Overriding verdict %r to 'possibly_outdated' (source year %d, age %d years).",
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
]:
    """
    Extract typed fields from a validated LLM response dict.

    Returns
    -------
    (verdict, explanation, llm_certainty, supporting_quote, time_sensitive, numbers_match)
    """
    verdict: VerdictLabel = llm_data["verdict"]  # type: ignore[assignment]
    explanation: str = llm_data["explanation"]
    llm_certainty: float = float(llm_data["llm_certainty"])
    supporting_quote: Optional[str] = llm_data.get("supporting_quote")
    time_sensitive: bool = bool(llm_data["time_sensitive"])
    numbers_match: bool = bool(llm_data["numbers_match"])
    return verdict, explanation, llm_certainty, supporting_quote, time_sensitive, numbers_match
