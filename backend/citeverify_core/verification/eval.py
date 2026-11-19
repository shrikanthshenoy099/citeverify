"""
verification/eval.py – Evaluation harness for the M3 verification engine.

Loads 20 labeled cases from data/mock/eval_set.json and runs verify() with
controlled (injected) LLM responses, passages and locate_quote stubs.
Prints a per-case result table and exits with code 0 only when ALL 20 pass.

Usage
-----
    python -m citeverify_core.verification.eval
    # or from repo root:
    python backend/citeverify_core/verification/eval.py

Requirements
------------
    All 20 cases must pass (verdict + flags match) for exit code 0.
    Any failure prints a detailed diff and exits with code 1.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

os.environ.setdefault("LLM_PROVIDER", "mock")

# Ensure the backend package is on sys.path when run as a script
_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND = _REPO_ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from citeverify_core.common.llm_client import LLMClient, LLMSchemaError
from citeverify_core.common.schemas import Claim, Evidence, Passage, Reference, Source
from citeverify_core.verification.engine import verify

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

_EVAL_SET_PATH = _REPO_ROOT / "data" / "mock" / "eval_set.json"


# ---------------------------------------------------------------------------
# Stub helpers
# ---------------------------------------------------------------------------

class _FixedLLM(LLMClient):
    """Returns a fixed dict or raises LLMSchemaError if sentinel is 'always_fail_schema'."""

    def __init__(self, response) -> None:
        self._response = response

    def complete_json(self, system: str, user: str, schema: dict, temperature: float = 0) -> dict:
        if self._response == "always_fail_schema":
            raise LLMSchemaError("simulated schema failure")
        return self._response


def _make_passages(texts: list[str], score: float = 0.88) -> list[Passage]:
    return [
        Passage(
            passage_id=f"p-{i:03d}",
            reference_id="eval-ref",
            text=t,
            page=1,
            section=None,
            score=score,
        )
        for i, t in enumerate(texts)
    ]


def _make_locate_fn(mode: str):
    """Return a locate_quote stub: 'found' returns an Evidence; 'none' returns None."""

    def _found(reference_id: str, quote: str) -> Optional[Evidence]:
        return Evidence(quote=quote, passage_id="p-000", page=1, section=None)

    def _none(reference_id: str, quote: str) -> Optional[Evidence]:
        return None

    return _found if mode == "found" else _none


# ---------------------------------------------------------------------------
# Case runner
# ---------------------------------------------------------------------------

def _run_case(case: dict) -> tuple[bool, str]:
    """
    Run a single eval case. Returns (passed: bool, detail: str).
    """
    case_id: str = case["id"]
    description: str = case["description"]

    # Build objects from JSON
    claim = Claim(**case["claim"])
    reference = Reference(**case["reference"])
    source = Source(**case["source"])

    # Passage score override (some cases specify a low score)
    passage_score: float = case.get("passages_with_score", 0.88)
    passages_fn = lambda ref_id, query, k=5: _make_passages(case["passages"], score=passage_score)  # noqa: E731

    llm_resp = case["llm_response"]
    llm = _FixedLLM(llm_resp)

    locate_mode: str = case.get("locate_quote_returns", "none")
    locate_fn = _make_locate_fn(locate_mode)

    verdict = verify(
        claim=claim,
        reference=reference,
        source=source,
        search_passages_fn=passages_fn,
        locate_quote_fn=locate_fn,
        llm_client=llm,
    )

    errors: list[str] = []

    # Check verdict label
    expected_verdict: str = case["expected_verdict"]
    if verdict.verdict != expected_verdict:
        errors.append(
            f"verdict: expected={expected_verdict!r} got={verdict.verdict!r}"
        )

    # Check flags that must be present
    for flag in case.get("expected_flags_include", []):
        if flag not in verdict.flags:
            errors.append(f"missing flag: {flag!r} (flags={verdict.flags})")

    # Check flags that must be absent
    for flag in case.get("expected_flags_exclude", []):
        if flag in verdict.flags:
            errors.append(f"unexpected flag: {flag!r} (flags={verdict.flags})")

    # Check confidence cap for abstract_only cases
    if "confidence_max" in case:
        if verdict.confidence > case["confidence_max"] + 1e-9:
            errors.append(
                f"confidence {verdict.confidence:.4f} exceeds cap {case['confidence_max']}"
            )

    # Check needs_human_review when explicitly specified
    if "needs_human_review" in case:
        expected_nhr: bool = case["needs_human_review"]
        if verdict.needs_human_review != expected_nhr:
            errors.append(
                f"needs_human_review: expected={expected_nhr} got={verdict.needs_human_review}"
            )

    passed = len(errors) == 0
    detail = ""
    if not passed:
        error_lines = "; ".join(errors)
        detail = f"[FAIL] {case_id} – {description}\n       {error_lines}"
    else:
        detail = f"[PASS] {case_id} – {description}"

    return passed, detail


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if not _EVAL_SET_PATH.exists():
        print(f"ERROR: eval set not found at {_EVAL_SET_PATH}", file=sys.stderr)
        sys.exit(1)

    with _EVAL_SET_PATH.open(encoding="utf-8") as fh:
        eval_cases: list[dict] = json.load(fh)

    total = len(eval_cases)
    passed_count = 0
    failed_count = 0

    print(f"\nCiteVerify M3 Evaluation – {total} cases\n{'=' * 60}")

    for case in eval_cases:
        ok, detail = _run_case(case)
        print(detail)
        if ok:
            passed_count += 1
        else:
            failed_count += 1

    print(f"\n{'=' * 60}")
    print(f"Results: {passed_count}/{total} passed", end="")
    if failed_count:
        print(f"  ({failed_count} FAILED)")
        sys.exit(1)
    else:
        print("  – ALL PASS")
        sys.exit(0)


if __name__ == "__main__":
    main()
