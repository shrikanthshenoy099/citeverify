#!/usr/bin/env python3
"""
verification/eval.py – Offline evaluation script for M3.

Runs every case in data/mock/eval_set.json through verify() using MockLLMClient
and reports accuracy, confusion matrix, and per-case failures.

Usage (from repo root):
    python backend/citeverify_core/verification/eval.py
    python backend/citeverify_core/verification/eval.py --json   # machine-readable output

The LLM is mocked: each eval case specifies the exact LLM response in its
"llm_mock" field, so results are fully deterministic.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

# Make sure the backend package is on sys.path when running from repo root
# Script lives at: <repo>/backend/citeverify_core/verification/eval.py
# parents: [0]=verification, [1]=citeverify_core, [2]=backend, [3]=repo_root
_repo_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_repo_root / "backend"))

os.environ.setdefault("LLM_PROVIDER", "mock")

from citeverify_core.common.llm_client import LLMSchemaError, MockLLMClient
from citeverify_core.common.schemas import Claim, Evidence, Passage, Reference, Source
from citeverify_core.verification.engine import verify

EVAL_SET_PATH = _repo_root / "data" / "mock" / "eval_set.json"

ALL_VERDICTS = [
    "supported", "partly_supported", "unsupported",
    "contradictory", "possibly_outdated", "needs_review",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_claim(c: dict) -> Claim:
    return Claim(**{k: v for k, v in c.items() if not k.startswith("_")})


def _make_reference(ref_id: str) -> Reference:
    return Reference(
        reference_id=ref_id,
        raw_text=f"Mock reference {ref_id}",
        title="Mock Paper",
        authors=["Mock Author"],
        year=2020,
        doi=f"10.1234/{ref_id}",
        parse_confidence=0.9,
    )


def _make_source(case: dict) -> Source:
    ref_id = case["claim"]["reference_ids"][0]
    return Source(
        reference_id=ref_id,
        matched=case.get("source_matched", True),
        match_score=0.9 if case.get("source_matched", True) else 0.0,
        title="Mock Paper",
        authors=["Mock Author"],
        year=case.get("source_year", 2020),
        doi=f"10.1234/{ref_id}",
        text_level=case.get("source_text_level", "full_text"),
        full_text_available=case.get("source_full_text_available", case.get("source_text_level") == "full_text"),
        source_database="eval",
        flags=case.get("source_flags", []),
    )


def _make_passages(case: dict) -> list[Passage]:
    ref_id = case["claim"]["reference_ids"][0]
    # Support both plain list and list-with-scores
    raw = case.get("passages_with_scores") or [
        {"text": t, "score": 0.75} for t in case.get("passages", [])
    ]
    return [
        Passage(
            passage_id=f"p-{i}",
            reference_id=ref_id,
            text=item["text"],
            page=None,
            section=None,
            score=item.get("score", 0.75),
        )
        for i, item in enumerate(raw)
    ]


def _make_llm(case: dict) -> Optional[MockLLMClient]:
    """Return a MockLLMClient configured with the case's llm_mock response."""
    mock_spec = case.get("llm_mock")
    if mock_spec is None:
        return None  # unmatched source → no LLM needed

    client = MockLLMClient()

    if mock_spec == "ALWAYS_INVALID":
        # Register a response that will FAIL schema validation every time
        client.register_mock(
            "__default__",
            {"bad_field": "this will never pass the schema"},
        )
        return client

    client.register_mock("__default__", mock_spec)
    return client


class _AlwaysInvalidLLM(MockLLMClient):
    """Raises LLMSchemaError on every call regardless of content."""
    def complete_json(self, system, user, schema, temperature=0):
        raise LLMSchemaError("Simulated always-invalid LLM response for eval case.")


# ---------------------------------------------------------------------------
# Run one case
# ---------------------------------------------------------------------------


def run_case(case: dict) -> dict:
    claim = _make_claim(case["claim"])
    ref_id = claim.reference_ids[0]
    reference = _make_reference(ref_id)
    source = _make_source(case)
    passages = _make_passages(case)

    llm_call_count = [0]

    def counting_search(reference_id, query, k=5):
        return passages

    def no_locate(reference_id, quote):
        # For eval cases that have quotes in passages → return evidence
        if any(quote.lower() in p.text.lower() for p in passages):
            return Evidence(
                quote=quote, passage_id="p-0", page=1, section="Results"
            )
        return None

    mock_spec = case.get("llm_mock")
    if mock_spec == "ALWAYS_INVALID":
        llm = _AlwaysInvalidLLM()
    else:
        llm = _make_llm(case)

    # Wrap LLM to count calls
    original_complete = llm.complete_json if llm else None

    def counting_llm(system, user, schema, temperature=0):
        llm_call_count[0] += 1
        return original_complete(system, user, schema, temperature)

    class WrappedLLM:
        def complete_json(self, system, user, schema, temperature=0):
            return counting_llm(system, user, schema, temperature)

    wrapped = WrappedLLM() if llm else _make_llm(case)

    verdict = verify(
        claim, reference, source,
        search_passages_fn=counting_search,
        locate_quote_fn=no_locate,
        llm_client=wrapped,
    )

    # Evaluate
    expected_verdict = case["expected_verdict"]
    expected_flags = set(case.get("expected_flags_include", []))
    expected_human_review = case.get("expected_human_review", False)
    expected_no_llm = case.get("expected_no_llm_call", False)
    expected_conf_max = case.get("expected_confidence_max")

    verdict_ok = verdict.verdict == expected_verdict
    flags_ok = expected_flags.issubset(set(verdict.flags))
    review_ok = verdict.needs_human_review == expected_human_review
    llm_ok = (not expected_no_llm) or (llm_call_count[0] == 0)
    conf_ok = expected_conf_max is None or verdict.confidence <= expected_conf_max + 0.001

    passed = verdict_ok and flags_ok and review_ok and llm_ok and conf_ok

    return {
        "case_id": case["case_id"],
        "description": case["description"],
        "passed": passed,
        "expected_verdict": expected_verdict,
        "got_verdict": verdict.verdict,
        "verdict_ok": verdict_ok,
        "expected_flags": sorted(expected_flags),
        "got_flags": sorted(verdict.flags),
        "flags_ok": flags_ok,
        "expected_human_review": expected_human_review,
        "got_human_review": verdict.needs_human_review,
        "review_ok": review_ok,
        "llm_call_count": llm_call_count[0],
        "llm_ok": llm_ok,
        "confidence": round(verdict.confidence, 3),
        "conf_ok": conf_ok,
    }


# ---------------------------------------------------------------------------
# Confusion matrix
# ---------------------------------------------------------------------------


def build_confusion_matrix(results: list[dict]) -> dict:
    matrix: dict[str, dict[str, int]] = {v: {w: 0 for w in ALL_VERDICTS} for v in ALL_VERDICTS}
    for r in results:
        exp = r["expected_verdict"]
        got = r["got_verdict"]
        if exp in matrix and got in matrix:
            matrix[exp][got] += 1
    return matrix


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="M3 offline evaluation")
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    parser.add_argument(
        "--eval-set", default=str(EVAL_SET_PATH),
        help="Path to eval_set.json"
    )
    args = parser.parse_args()

    eval_path = Path(args.eval_set)
    if not eval_path.exists():
        print(f"ERROR: eval set not found: {eval_path}", file=sys.stderr)
        sys.exit(1)

    cases = json.loads(eval_path.read_text(encoding="utf-8"))
    results = [run_case(c) for c in cases]

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    failed = total - passed
    accuracy = passed / total if total else 0.0

    matrix = build_confusion_matrix(results)
    failures = [r for r in results if not r["passed"]]

    if args.json:
        print(json.dumps({
            "total": total, "passed": passed, "failed": failed,
            "accuracy": accuracy,
            "confusion_matrix": matrix,
            "failures": failures,
        }, indent=2))
        return

    # Human-readable output
    print(f"\n{'='*60}")
    print(f"M3 Verification Engine — Evaluation Results")
    print(f"{'='*60}")
    print(f"Total: {total}  Passed: {passed}  Failed: {failed}  "
          f"Accuracy: {accuracy*100:.1f}%\n")

    # Confusion matrix (compact)
    short = {v: v[:8] for v in ALL_VERDICTS}
    header = f"{'Expected vs Got':<18}" + "".join(f"{short[v]:>12}" for v in ALL_VERDICTS)
    print(header)
    print("-" * len(header))
    for exp in ALL_VERDICTS:
        row = f"{short[exp]:<18}" + "".join(
            f"{matrix[exp][got]:>12}" for got in ALL_VERDICTS
        )
        print(row)
    print()

    if failures:
        print(f"FAILURES ({len(failures)}):")
        for f in failures:
            print(f"  [{f['case_id']}] {f['description']}")
            if not f["verdict_ok"]:
                print(f"    verdict:  expected={f['expected_verdict']}  got={f['got_verdict']}")
            if not f["flags_ok"]:
                print(f"    flags:    expected_subset={f['expected_flags']}  got={f['got_flags']}")
            if not f["review_ok"]:
                print(f"    review:   expected={f['expected_human_review']}  got={f['got_human_review']}")
            if not f["llm_ok"]:
                print(f"    llm_calls:{f['llm_call_count']} (expected 0)")
            if not f["conf_ok"]:
                print(f"    confidence:{f['confidence']} exceeds max")
    else:
        print("All cases passed!")

    print(f"\n{'='*60}\n")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
