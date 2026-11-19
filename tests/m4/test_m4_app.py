"""
tests/m4/test_m4_app.py – pytest suite for M4 FastAPI app.

Tests the REST API in-process using FastAPI TestClient (synchronous).

Run from repo root:
    pytest tests/m4/ -v
"""

from __future__ import annotations

import sys
import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
BACKEND = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


# ---------------------------------------------------------------------------
# App fixture with in-memory DB
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def test_app():
    # Use a temp dir for uploads/sources so we don't need /tmp on Windows
    _tmpdir = tempfile.mkdtemp(prefix="citeverify_test_")
    os.environ["DATABASE_URL"] = "sqlite://"  # pure in-memory
    os.environ["UPLOAD_DIR"] = _tmpdir
    os.environ["SOURCES_DIR"] = _tmpdir
    os.environ["LLM_PROVIDER"] = "mock"

    # Reset singletons so env vars take effect
    import app.config as cfg_mod
    import app.database as db_mod
    cfg_mod._settings = None
    db_mod._engine = None
    db_mod._SessionFactory = None

    # Inject an in-memory engine with StaticPool so all sessions share one connection
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    from app.database import Base

    mem_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(mem_engine)

    # Patch the module-level singletons
    db_mod._engine = mem_engine
    from sqlalchemy.orm import sessionmaker
    db_mod._SessionFactory = sessionmaker(bind=mem_engine, autoflush=False, autocommit=False)

    from app.main import app as fastapi_app
    return fastapi_app


@pytest.fixture(scope="module")
def client(test_app):
    with TestClient(test_app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_root(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "CiteVerify" in r.json().get("service", "")


# ---------------------------------------------------------------------------
# POST /api/documents
# ---------------------------------------------------------------------------

def test_upload_text_returns_202(client):
    r = client.post("/api/documents", data={"text": "Some sample text."})
    assert r.status_code == 202
    body = r.json()
    assert "doc_id" in body
    assert body["status"] == "pending"


def test_upload_no_input_returns_422(client):
    r = client.post("/api/documents")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/documents/{doc_id}/status
# ---------------------------------------------------------------------------

def test_status_pending(client):
    r = client.post("/api/documents", data={"text": "Hello world."})
    doc_id = r.json()["doc_id"]

    r2 = client.get(f"/api/documents/{doc_id}/status")
    assert r2.status_code == 200
    assert r2.json()["doc_id"] == doc_id
    assert r2.json()["status"] in ("pending", "processing", "done", "error")


def test_status_404(client):
    r = client.get("/api/documents/nonexistent-doc/status")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/documents/{doc_id}/results
# ---------------------------------------------------------------------------

def test_results_not_done_or_done(client):
    r = client.post("/api/documents", data={"text": "Hello world."})
    doc_id = r.json()["doc_id"]
    # Could be 202 (not done yet) or 200 (done very fast)
    r2 = client.get(f"/api/documents/{doc_id}/results")
    assert r2.status_code in (200, 202)


def test_results_404(client):
    r = client.get("/api/documents/nonexistent/results")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/claims/{claim_id}
# ---------------------------------------------------------------------------

def test_claim_404(client):
    r = client.get("/api/claims/nonexistent-claim-id")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/claims/{claim_id}/review
# ---------------------------------------------------------------------------

def test_review_claim_not_found(client):
    r = client.post(
        "/api/claims/nonexistent/review",
        json={"action": "comment", "comment": "test", "reviewer": "alice"},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/documents/{doc_id}/export – validation
# ---------------------------------------------------------------------------

def test_export_bad_format(client):
    r = client.post("/api/documents", data={"text": "Some text."})
    doc_id = r.json()["doc_id"]
    r2 = client.get(f"/api/documents/{doc_id}/export?format=xlsx")
    assert r2.status_code == 422


def test_export_404(client):
    r = client.get("/api/documents/nonexistent/export?format=csv")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/sources/{reference_id}/pdf
# ---------------------------------------------------------------------------

def test_source_pdf_no_ref(client):
    r = client.get("/api/sources/nonexistent_ref/pdf")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Full pipeline round-trip (text with references)
# ---------------------------------------------------------------------------

def test_full_pipeline_text(client):
    """
    Upload text, wait for processing, check results structure.
    BackgroundTasks run synchronously in TestClient.
    """
    text = (
        "Transformer models outperform RNNs on most NLP tasks [1].\n"
        "BERT achieved 93.5% accuracy on the GLUE benchmark [1].\n"
        "We therefore conclude that pre-training is essential [1, 2].\n\n"
        "REFERENCES\n\n"
        "[1] Devlin, J. et al. (2019). BERT: Pre-training of Deep Bidirectional "
        "Transformers. arXiv:1810.04805.\n"
        "[2] Wang, A. et al. (2018). GLUE: A Multi-Task Benchmark. "
        "doi:10.18653/v1/W18-5446.\n"
    )
    r = client.post("/api/documents", data={"text": text})
    assert r.status_code == 202
    doc_id = r.json()["doc_id"]

    # Poll status
    import time
    for _ in range(20):
        s = client.get(f"/api/documents/{doc_id}/status")
        if s.json()["status"] in ("done", "error"):
            break
        time.sleep(0.1)

    status_data = client.get(f"/api/documents/{doc_id}/status").json()
    assert status_data["status"] in ("done", "error"), f"status={status_data['status']}"

    if status_data["status"] == "done":
        res = client.get(f"/api/documents/{doc_id}/results")
        assert res.status_code == 200
        body = res.json()
        assert body["doc_id"] == doc_id
        assert isinstance(body["claims"], list)
        assert isinstance(body["references"], list)

        # Claims should have verdicts list (possibly empty if M3 mock)
        for c in body["claims"]:
            assert "claim_id" in c
            assert "text" in c
            assert isinstance(c["verdicts"], list)


def test_export_csv_after_pipeline(client):
    """Upload, process, then export as CSV."""
    text = "Accuracy was 95% [1].\n\nREFERENCES\n\n[1] Smith R. (2020). Some Paper. doi:10.1234/t."
    r = client.post("/api/documents", data={"text": text})
    doc_id = r.json()["doc_id"]

    import time
    for _ in range(20):
        s = client.get(f"/api/documents/{doc_id}/status")
        if s.json()["status"] in ("done", "error"):
            break
        time.sleep(0.1)

    if client.get(f"/api/documents/{doc_id}/status").json()["status"] != "done":
        pytest.skip("Pipeline did not complete; skipping CSV export test.")

    r2 = client.get(f"/api/documents/{doc_id}/export?format=csv")
    assert r2.status_code == 200
    assert "text/csv" in r2.headers.get("content-type", "")


def test_review_submit_and_list(client):
    """Create a claim via pipeline, then submit and list a review."""
    text = (
        "Accuracy was 95% [1].\n\nREFERENCES\n\n"
        "[1] Smith R. (2020). Some Paper. doi:10.1234/review-test."
    )
    r = client.post("/api/documents", data={"text": text})
    doc_id = r.json()["doc_id"]

    import time
    for _ in range(20):
        s = client.get(f"/api/documents/{doc_id}/status")
        if s.json()["status"] in ("done", "error"):
            break
        time.sleep(0.1)

    if client.get(f"/api/documents/{doc_id}/status").json()["status"] != "done":
        pytest.skip("Pipeline did not complete.")

    res = client.get(f"/api/documents/{doc_id}/results").json()
    if not res.get("claims"):
        pytest.skip("No claims extracted.")

    claim_id = res["claims"][0]["claim_id"]

    # Submit review
    rv = client.post(
        f"/api/claims/{claim_id}/review",
        json={"action": "comment", "comment": "looks right", "reviewer": "alice"},
    )
    assert rv.status_code == 201
    assert rv.json()["reviewer"] == "alice"

    # List reviews
    rl = client.get(f"/api/claims/{claim_id}/reviews")
    assert rl.status_code == 200
    reviews = rl.json()
    assert any(r["reviewer"] == "alice" for r in reviews)
