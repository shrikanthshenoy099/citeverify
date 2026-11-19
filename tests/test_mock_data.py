"""
tests/test_mock_data.py – Validates data/mock/*.json against schemas.py.

Ensures the canned demo data always conforms to the contracts, so the
highlight viewer and UI demo are guaranteed to work.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from citeverify_core.common.schemas import (
    ParsedDocument,
    Verdict,
)

MOCK_DIR = Path(__file__).parent.parent / "data" / "mock"


def test_demo_document_valid():
    """data/mock/demo_document.json validates as ParsedDocument."""
    path = MOCK_DIR / "demo_document.json"
    assert path.exists(), f"Missing {path}"
    data = json.loads(path.read_text())
    doc = ParsedDocument(**data)
    assert len(doc.claims) >= 1
    assert len(doc.references) >= 1


def test_demo_verdicts_valid():
    """data/mock/demo_verdicts.json validates as list[Verdict]."""
    path = MOCK_DIR / "demo_verdicts.json"
    assert path.exists(), f"Missing {path}"
    data = json.loads(path.read_text())
    verdicts = [Verdict(**v) for v in data]
    assert len(verdicts) >= 4


def test_demo_verdicts_has_bbox_evidence():
    """At least one Verdict in demo_verdicts.json has bboxes (for highlight viewer)."""
    path = MOCK_DIR / "demo_verdicts.json"
    data = json.loads(path.read_text())
    has_bboxes = any(
        v.get("evidence") and v["evidence"].get("bboxes")
        for v in data
    )
    assert has_bboxes, "No Verdict in demo_verdicts.json has bboxes – PdfHighlightViewer cannot be tested"


def test_demo_verdicts_cover_all_labels():
    """The demo verdicts cover supported, partly_supported, contradictory, needs_review."""
    path = MOCK_DIR / "demo_verdicts.json"
    data = json.loads(path.read_text())
    labels = {v["verdict"] for v in data}
    for expected in ("supported", "partly_supported", "contradictory", "needs_review"):
        assert expected in labels, f"Missing verdict label '{expected}' in demo_verdicts.json"


def test_no_citation_claim_in_demo():
    """demo_document.json has at least one claim with empty reference_ids."""
    path = MOCK_DIR / "demo_document.json"
    data = json.loads(path.read_text())
    uncited = [c for c in data["claims"] if not c.get("reference_ids")]
    assert len(uncited) >= 1, "No uncited claim found in demo_document.json"
