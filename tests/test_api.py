"""
tests/test_api.py – Integration tests for the M4 FastAPI backend.

Tests:
  - Pipeline end-to-end with mocks
  - Reviews are append-only (two reviews → both persist)
  - Upload validation (wrong type, oversize)
  - Orchestrator resilience (one item raises → pipeline still completes)
  - no_citation claim gets a verdict
  - CSV export columns
"""

from __future__ import annotations

import io
import json
import os
import time
import uuid

import pytest

os.environ["USE_MOCKS"] = "true"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.db.models import Base
from app.db.session import get_db

# ---------------------------------------------------------------------------
# In-memory SQLite database for each test
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    """Create a fresh TestClient with an in-memory DB for each test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wait_for_done(client: TestClient, doc_id: str, timeout: float = 10.0) -> str:
    """Poll status until terminal; return final status."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/documents/{doc_id}/status")
        status = r.json()["status"]
        if status in ("done", "error"):
            return status
        time.sleep(0.05)
    return "timeout"


# ---------------------------------------------------------------------------
# A. Health check
# ---------------------------------------------------------------------------

def test_health(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# B. Pipeline end-to-end with mocks
# ---------------------------------------------------------------------------

def test_text_submission_pipeline(client: TestClient):
    """POST text → pipeline runs → results contain claims and verdicts."""
    r = client.post("/api/documents", data={"text": "Some scientific text."})
    assert r.status_code == 202
    doc_id = r.json()["doc_id"]

    final = _wait_for_done(client, doc_id)
    assert final == "done", f"Expected done, got {final}"

    r = client.get(f"/api/documents/{doc_id}/results")
    assert r.status_code == 200
    body = r.json()
    assert len(body["claims"]) >= 1

    # Every claim should have at least one verdict
    for claim in body["claims"]:
        assert len(claim["verdicts"]) >= 1, (
            f"Claim {claim['claim_id']} has no verdicts"
        )


def test_no_citation_claim_gets_verdict(client: TestClient):
    """The mock produces a claim with no reference_ids – orchestrator creates no_citation verdict."""
    r = client.post("/api/documents", data={"text": "Demo text."})
    doc_id = r.json()["doc_id"]
    _wait_for_done(client, doc_id)

    r = client.get(f"/api/documents/{doc_id}/results")
    claims = r.json()["claims"]
    uncited = [c for c in claims if not c["reference_ids"]]
    assert len(uncited) >= 1, "Expected at least one uncited claim"
    for c in uncited:
        assert len(c["verdicts"]) >= 1
        v = c["verdicts"][0]
        assert v["reference_id"] == "__no_citation__"
        assert "no_citation" in v["flags"]
        assert v["needs_human_review"] is True


def test_pipeline_status_progression(client: TestClient):
    """Status endpoint returns a known status string."""
    r = client.post("/api/documents", data={"text": "Some text."})
    doc_id = r.json()["doc_id"]
    r2 = client.get(f"/api/documents/{doc_id}/status")
    assert r2.status_code == 200
    assert r2.json()["status"] in ("pending", "parsing", "retrieving", "verifying", "done", "error")


# ---------------------------------------------------------------------------
# C. Reviews are append-only
# ---------------------------------------------------------------------------

def test_reviews_append_only(client: TestClient):
    """Submit two reviews on the same (claim, reference) – both persist in history."""
    r = client.post("/api/documents", data={"text": "Demo."})
    doc_id = r.json()["doc_id"]
    _wait_for_done(client, doc_id)

    results = client.get(f"/api/documents/{doc_id}/results").json()
    claim = results["claims"][0]
    claim_id = claim["claim_id"]
    ref_id = claim["verdicts"][0]["reference_id"]

    for i, action in enumerate(["accept", "comment"]):
        r = client.post(
            f"/api/claims/{claim_id}/review",
            json={
                "reference_id": ref_id,
                "action": action,
                "comment": f"Review {i + 1}",
                "reviewer": f"Reviewer{i + 1}",
            },
        )
        assert r.status_code == 201, r.text

    history = client.get(f"/api/claims/{claim_id}/reviews").json()
    assert len(history) == 2, f"Expected 2 reviews, got {len(history)}: {history}"
    actions = {r["action"] for r in history}
    assert "accept" in actions
    assert "comment" in actions


# ---------------------------------------------------------------------------
# D. Upload validation
# ---------------------------------------------------------------------------

def test_upload_wrong_extension_rejected(client: TestClient):
    r = client.post(
        "/api/documents",
        files={"file": ("report.txt", b"hello world", "text/plain")},
    )
    assert r.status_code == 400


def test_upload_no_input_rejected(client: TestClient):
    r = client.post("/api/documents")
    assert r.status_code == 422


def test_upload_pdf_accepted(client: TestClient):
    # Minimal valid-enough PDF bytes (1-byte body; upload validation checks ext only)
    r = client.post(
        "/api/documents",
        files={"file": ("paper.pdf", b"%PDF-1.4 1 0 obj", "application/pdf")},
    )
    assert r.status_code == 202


def test_upload_docx_accepted(client: TestClient):
    r = client.post(
        "/api/documents",
        files={
            "file": (
                "paper.docx",
                b"PK" + b"\x00" * 20,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert r.status_code == 202


# ---------------------------------------------------------------------------
# E. Orchestrator resilience
# ---------------------------------------------------------------------------

def test_pipeline_continues_when_verify_raises(client: TestClient, monkeypatch):
    """
    Monkeypatch mock_verify to raise on the first call; the pipeline must still
    complete (status=done) and produce an error-sentinel verdict.
    """
    import app.mocks as mocks_module

    call_count = [0]
    original = mocks_module.mock_verify

    def flaky_verify(claim, reference, source):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("Simulated verify failure")
        return original(claim, reference, source)

    monkeypatch.setattr(mocks_module, "mock_verify", flaky_verify)

    r = client.post("/api/documents", data={"text": "Some text."})
    doc_id = r.json()["doc_id"]
    final = _wait_for_done(client, doc_id)
    assert final == "done", f"Pipeline should not abort on a single verify failure, got: {final}"

    results = client.get(f"/api/documents/{doc_id}/results").json()
    # At least one claim should have a llm_output_invalid or needs_review verdict
    all_flags = [
        flag
        for c in results["claims"]
        for v in c["verdicts"]
        for flag in v.get("flags", [])
    ]
    assert "llm_output_invalid" in all_flags, (
        f"Expected llm_output_invalid flag on error verdict; got flags: {all_flags}"
    )


# ---------------------------------------------------------------------------
# F. CSV export
# ---------------------------------------------------------------------------

def test_csv_export_columns(client: TestClient):
    """CSV export must include required columns including evidence_quote and disclaimer."""
    r = client.post("/api/documents", data={"text": "Some text."})
    doc_id = r.json()["doc_id"]
    _wait_for_done(client, doc_id)

    r = client.get(f"/api/documents/{doc_id}/export?format=csv")
    assert r.status_code == 200
    content = r.text

    # Disclaimer row
    assert "Not a final academic judgment" in content

    # Required columns
    for col in [
        "claim_id", "claim_text", "verdict", "confidence",
        "evidence_quote", "evidence_page", "flags",
        "latest_review_action",
    ]:
        assert col in content, f"CSV missing column: {col}"


# ---------------------------------------------------------------------------
# G. 404s
# ---------------------------------------------------------------------------

def test_unknown_document_returns_404(client: TestClient):
    r = client.get("/api/documents/nonexistent-id/status")
    assert r.status_code == 404


def test_unknown_claim_returns_404(client: TestClient):
    r = client.get("/api/claims/nonexistent-claim-id")
    assert r.status_code == 404
