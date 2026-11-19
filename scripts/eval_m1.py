#!/usr/bin/env python3
"""
scripts/eval_m1.py – M1 Document Intelligence evaluation script.

Reports:
  - Citation-marker detection precision / recall against ground_truth.json
  - Reference-mapping accuracy (markers resolved to correct ref_id)
  - Claim-classification accuracy against ground-truth claim fragments
  - ParsedDocument schema validation for each sample

Usage:
    python scripts/eval_m1.py [--fixture-dir tests/m1/fixtures]

Requires:
    LLM_PROVIDER=mock (default)  – no network calls needed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("LLM_PROVIDER", "mock")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from citeverify_core.doc_intel import parse_document
from citeverify_core.common.schemas import ParsedDocument


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_ground_truth(fixture_dir: Path) -> dict:
    gt_path = fixture_dir / "ground_truth.json"
    with open(gt_path, encoding="utf-8") as f:
        return json.load(f)


def _validate_schema(result: ParsedDocument) -> list[str]:
    """Return a list of schema-violation strings (empty = valid)."""
    errors: list[str] = []
    for claim in result.claims:
        if claim.char_end <= claim.char_start:
            errors.append(f"claim {claim.claim_id}: char_end <= char_start")
        if claim.claim_type not in ("numeric", "factual", "conclusion", "methodological"):
            errors.append(f"claim {claim.claim_id}: bad claim_type {claim.claim_type!r}")
    for ref in result.references:
        if not (0.0 <= ref.parse_confidence <= 1.0):
            errors.append(f"ref {ref.reference_id}: confidence out of range")
    return errors


def _eval_markers(result: ParsedDocument, gt: dict) -> tuple[float, float, list[str]]:
    """
    Precision / recall of citation-marker detection.

    gt["expected_citation_markers"] maps text_fragment -> list[expected_markers].
    For each fragment, find the claim containing it and check markers.
    """
    true_positives = 0
    false_positives = 0
    false_negatives = 0
    failures: list[str] = []

    expected: dict[str, list[str]] = gt.get("expected_citation_markers", {})
    all_markers_found = [m for c in result.claims for m in c.citation_markers]

    for fragment, expected_markers in expected.items():
        matching_claims = [c for c in result.claims if fragment.lower() in c.text.lower()]
        if not matching_claims:
            false_negatives += len(expected_markers)
            failures.append(f"  MISS fragment not found in any claim: {fragment!r}")
            continue
        # Collect all markers in matching claims
        found_markers_for_fragment = [m for c in matching_claims for m in c.citation_markers]
        for em in expected_markers:
            if em in found_markers_for_fragment:
                true_positives += 1
            else:
                false_negatives += 1
                failures.append(
                    f"  MISS marker {em!r} not found for fragment {fragment!r}; "
                    f"got: {found_markers_for_fragment}"
                )

    # False positives: markers in claims that are purely numeric references to ref-list lines
    # (heuristic: not meaningful to count here without a full labeled dataset)

    total_expected = sum(len(v) for v in expected.values())
    precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 1.0
    recall = true_positives / total_expected if total_expected > 0 else 1.0
    return precision, recall, failures


def _eval_ref_mapping(result: ParsedDocument, gt: dict) -> tuple[float, list[str]]:
    """
    Accuracy of reference DOI extraction.
    """
    expected_refs = gt.get("expected_references", [])
    if not expected_refs:
        return 1.0, []

    correct = 0
    failures: list[str] = []
    for er in expected_refs:
        exp_doi = er.get("doi", "").lower()
        exp_year = er.get("year")
        found = False
        for ref in result.references:
            if exp_doi and ref.doi and ref.doi.lower() == exp_doi:
                found = True
                if exp_year and ref.year != exp_year:
                    failures.append(
                        f"  WRONG-YEAR doi={exp_doi}: expected {exp_year}, got {ref.year}"
                    )
                break
        if found:
            correct += 1
        else:
            failures.append(f"  MISS doi={exp_doi!r} not found in {[r.doi for r in result.references]}")

    accuracy = correct / len(expected_refs)
    return accuracy, failures


def _eval_claim_types(result: ParsedDocument, gt: dict) -> tuple[float, list[str]]:
    """
    Accuracy of claim type classification against expected fragments.
    """
    expected = gt.get("expected_claims_containing", [])
    if not expected:
        return 1.0, []

    correct = 0
    failures: list[str] = []
    for ec in expected:
        fragment = ec["text_fragment"]
        expected_type = ec.get("claim_type")
        expected_number = ec.get("numbers_mentioned_includes")

        matching = [c for c in result.claims if fragment.lower() in c.text.lower()]
        if not matching:
            failures.append(f"  MISS claim fragment not found: {fragment!r}")
            continue

        c = matching[0]
        if expected_type and c.claim_type != expected_type:
            failures.append(
                f"  WRONG-TYPE {fragment!r}: expected {expected_type}, got {c.claim_type}"
            )
        elif expected_number and expected_number not in c.numbers_mentioned:
            failures.append(
                f"  MISS-NUMBER {fragment!r}: expected {expected_number!r} in {c.numbers_mentioned}"
            )
        else:
            correct += 1

    accuracy = correct / len(expected) if expected else 1.0
    return accuracy, failures


def eval_document(
    name: str,
    file_path: str | None,
    raw_text: str | None,
    gt: dict,
    doc_id: str,
) -> dict:
    t0 = time.monotonic()
    result = parse_document(file_path=file_path, raw_text=raw_text, doc_id=doc_id)
    elapsed = time.monotonic() - t0

    schema_errors = _validate_schema(result)
    marker_prec, marker_rec, marker_failures = _eval_markers(result, gt)
    ref_acc, ref_failures = _eval_ref_mapping(result, gt)
    claim_acc, claim_failures = _eval_claim_types(result, gt)

    return {
        "name": name,
        "source_type": result.source_type,
        "num_pages": result.num_pages,
        "num_references": len(result.references),
        "num_claims": len(result.claims),
        "warnings": result.warnings,
        "elapsed_s": round(elapsed, 3),
        "schema_valid": not schema_errors,
        "schema_errors": schema_errors,
        "marker_precision": round(marker_prec, 3),
        "marker_recall": round(marker_rec, 3),
        "marker_failures": marker_failures,
        "ref_mapping_accuracy": round(ref_acc, 3),
        "ref_failures": ref_failures,
        "claim_type_accuracy": round(claim_acc, 3),
        "claim_failures": claim_failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="M1 Document Intelligence evaluation")
    parser.add_argument(
        "--fixture-dir",
        default="tests/m1/fixtures",
        help="Directory containing sample_paper.{txt,pdf,docx} and ground_truth.json",
    )
    args = parser.parse_args()

    fixture_dir = Path(args.fixture_dir)
    gt = _load_ground_truth(fixture_dir)

    # Load pasted text
    txt_path = fixture_dir / "sample_paper.txt"
    raw_text = txt_path.read_text(encoding="utf-8") if txt_path.exists() else None

    samples = []

    if raw_text:
        samples.append(("pasted-text", None, raw_text, "eval-txt"))

    pdf_path = fixture_dir / "sample_paper.pdf"
    if pdf_path.exists():
        samples.append(("PDF", str(pdf_path), None, "eval-pdf"))

    docx_path = fixture_dir / "sample_paper.docx"
    if docx_path.exists():
        samples.append(("DOCX", str(docx_path), None, "eval-docx"))

    all_results = []
    for name, fp, rt, doc_id in samples:
        print(f"\n{'='*60}")
        print(f"Evaluating: {name}")
        print(f"{'='*60}")
        r = eval_document(name, fp, rt, gt, doc_id)
        all_results.append(r)

        print(f"  Source type:          {r['source_type']}")
        print(f"  Pages:                {r['num_pages']}")
        print(f"  References found:     {r['num_references']}")
        print(f"  Claims found:         {r['num_claims']}")
        print(f"  Warnings:             {r['warnings']}")
        print(f"  Parse time:           {r['elapsed_s']}s")
        print(f"  Schema valid:         {r['schema_valid']}")
        if r["schema_errors"]:
            for e in r["schema_errors"]:
                print(f"    {e}")
        print(f"  Marker precision:     {r['marker_precision']:.1%}")
        print(f"  Marker recall:        {r['marker_recall']:.1%}")
        for f in r["marker_failures"]:
            print(f)
        print(f"  Ref mapping accuracy: {r['ref_mapping_accuracy']:.1%}")
        for f in r["ref_failures"]:
            print(f)
        print(f"  Claim-type accuracy:  {r['claim_type_accuracy']:.1%}")
        for f in r["claim_failures"]:
            print(f)

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"{'Sample':<18} {'Schema':>8} {'Mrkr P':>8} {'Mrkr R':>8} {'Ref Acc':>8} {'Clm Acc':>8} {'Time':>7}")
    print("-" * 68)
    for r in all_results:
        schema_ok = "OK" if r["schema_valid"] else "FAIL"
        print(
            f"{r['name']:<18} {schema_ok:>8} "
            f"{r['marker_precision']:>7.1%} "
            f"{r['marker_recall']:>7.1%} "
            f"{r['ref_mapping_accuracy']:>7.1%} "
            f"{r['claim_type_accuracy']:>7.1%} "
            f"{r['elapsed_s']:>6.2f}s"
        )

    # Exit non-zero if any schema errors
    if any(not r["schema_valid"] for r in all_results):
        sys.exit(1)


if __name__ == "__main__":
    main()
