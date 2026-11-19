"""
tests/m4/test_api.py – FastAPI endpoint tests for M4.

Uses an in-memory SQLite DB and TestClient so no server is needed.
M1/M2 are not needed; we bypass the pipeline with direct DB inserts.
"""

from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ["DATABASE_URL"] = "sqlite://"  # in-memory

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import create_app
import app.models  # noqa: F401 – registers ORM models on Base before create_all
from app.models import ClaimRecord, DocumentRecord, ReferenceRecord, ReviewRecord, VerdictRecord


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    """TestClient wired to a shared in-memory SQLite DB (StaticPool)."""
    # StaticPool ensures all connections share the same in-memory database
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    app = create_app()

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        c._session_factory = TestingSessionLocal
        yield c


@pytest.fixture()
def seeded_doc(client):
    """Insert a completed document with one claim + one verdict into the test DB."""
    db = client._session_factory()
    doc_id = str(uuid.uuid4())
    claim_id = str(uuid.uuid4())
    ref_id = str(uuid.uuid4())

    doc = DocumentRecord(
        doc_id=doc_id,
        source_type="text",
        status="done",
        num_pages=None,
        warnings=[],
    )
    ref = ReferenceRecord(
        reference_id=ref_id,
        doc_id=doc_id,
        raw_text="Smith (2020) Great Paper.",
        title="Great Paper",
        authors=["Smith, J."],
        year=2020,
        doi="10.1234/great",
        matched=True,
        source_title="Great Paper",
        text_level="full_text",
        source_flags=[],
    )
    claim = ClaimRecord(
        claim_id=claim_id,
        doc_id=doc_id,
        text="Accuracy was 95%.",
        char_start=0,
        char_end=18,
        claim_type="numeric",
        citation_markers=["[1]"],
        reference_ids=[ref_id],
        numbers_mentioned=["95%"],
        context_before="",
        context_after="",
        flags=[],
    )
    verdict = VerdictRecord(
        claim_id=claim_id,
        reference_id=ref_id,
        verdict="supported",
        explanation="The source confirms 95% accuracy.",
        confidence=0.85,
        needs_human_review=False,
        flags=[],
        verdict_json={
            "claim_id": claim_id,
            "reference_id": ref_id,
            "verdict": "supported",
            "explanation": "The source confirms 95% accuracy.",
            "confidence": 0.85,
            "needs_human_review": False,
            "flags": [],
            "confidence_breakdown": {
                "retrieval": 0.88,
                "llm_certainty": 0.9,
                "text_match": 1.0,
                "full_text": 1.0,
                "numeric_match": 1.0,
            },
            "source_trace": {"doi": "10.1234/great", "url": None, "page": 5, "section": "Results"},
        },
    )

    db.add_all([doc, ref, claim, verdict])
    db.commit()
    db.close()
    return {"doc_id": doc_id, "claim_id": claim_id, "ref_id": ref_id}


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


class TestHealth:
    def test_health_ok(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "disclaimer" in data


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


class TestDocumentStatus:
    def test_404_unknown_doc(self, client):
        r = client.get("/api/documents/does-not-exist/status")
        assert r.status_code == 404

    def test_status_returns_expected_fields(self, client, seeded_doc):
        r = client.get(f"/api/documents/{seeded_doc['doc_id']}/status")
        assert r.status_code == 200
        data = r.json()
        assert data["doc_id"] == seeded_doc["doc_id"]
        assert data["status"] == "done"
        assert "warnings" in data


class TestDocumentResults:
    def test_404_unknown_doc(self, client):
        r = client.get("/api/documents/does-not-exist/results")
        assert r.status_code == 404

    def test_results_contains_claims_and_verdicts(self, client, seeded_doc):
        r = client.get(f"/api/documents/{seeded_doc['doc_id']}/results")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "done"
        assert len(data["claims"]) == 1
        claim = data["claims"][0]
        assert claim["claim_id"] == seeded_doc["claim_id"]
        assert len(claim["verdicts"]) == 1
        verdict = claim["verdicts"][0]
        assert verdict["verdict"] == "supported"
        assert verdict["confidence"] == pytest.approx(0.85)
        assert verdict["needs_human_review"] is False


class TestDocumentExportCSV:
    def test_csv_export(self, client, seeded_doc):
        r = client.get(f"/api/documents/{seeded_doc['doc_id']}/export?format=csv")
        assert r.status_code == 200
        assert "text/csv" in r.headers["content-type"]
        content = r.text
        assert "claim_id" in content
        assert "verdict" in content

    def test_invalid_format(self, client, seeded_doc):
        r = client.get(f"/api/documents/{seeded_doc['doc_id']}/export?format=xml")
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------


class TestClaimDetail:
    def test_404_unknown_claim(self, client):
        r = client.get("/api/claims/does-not-exist")
        assert r.status_code == 404

    def test_claim_returns_full_detail(self, client, seeded_doc):
        r = client.get(f"/api/claims/{seeded_doc['claim_id']}")
        assert r.status_code == 200
        data = r.json()
        assert data["claim_id"] == seeded_doc["claim_id"]
        assert "text" in data
        assert "verdicts" in data


class TestReviews:
    def test_submit_review(self, client, seeded_doc):
        payload = {
            "reference_id": seeded_doc["ref_id"],
            "action": "accept",
            "comment": "Looks correct.",
            "reviewer": "Dr. Smith",
        }
        r = client.post(f"/api/claims/{seeded_doc['claim_id']}/review", json=payload)
        assert r.status_code == 201
        data = r.json()
        assert data["action"] == "accept"
        assert data["reviewer"] == "Dr. Smith"
        assert "review_id" in data

    def test_submit_override_requires_new_verdict(self, client, seeded_doc):
        payload = {
            "reference_id": seeded_doc["ref_id"],
            "action": "override",
            "comment": "Wrong verdict.",
            "reviewer": "Dr. Jones",
            # new_verdict deliberately omitted
        }
        r = client.post(f"/api/claims/{seeded_doc['claim_id']}/review", json=payload)
        assert r.status_code == 422

    def test_submit_override_with_valid_verdict(self, client, seeded_doc):
        payload = {
            "reference_id": seeded_doc["ref_id"],
            "action": "override",
            "new_verdict": "unsupported",
            "comment": "I checked the original; not supported.",
            "reviewer": "Dr. Jones",
        }
        r = client.post(f"/api/claims/{seeded_doc['claim_id']}/review", json=payload)
        assert r.status_code == 201
        data = r.json()
        assert data["new_verdict"] == "unsupported"

    def test_list_reviews(self, client, seeded_doc):
        # Submit one first
        client.post(
            f"/api/claims/{seeded_doc['claim_id']}/review",
            json={
                "reference_id": seeded_doc["ref_id"],
                "action": "comment",
                "comment": "Noted.",
                "reviewer": "Reviewer X",
            },
        )
        r = client.get(f"/api/claims/{seeded_doc['claim_id']}/reviews")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        assert len(r.json()) >= 1

    def test_empty_reviewer_rejected(self, client, seeded_doc):
        payload = {
            "reference_id": seeded_doc["ref_id"],
            "action": "comment",
            "comment": "Anonymous?",
            "reviewer": "   ",   # whitespace-only
        }
        r = client.post(f"/api/claims/{seeded_doc['claim_id']}/review", json=payload)
        assert r.status_code == 422
