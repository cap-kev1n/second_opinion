"""Tests for verification run lifecycle, persistence, and reporting endpoints."""

import hashlib
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from main import app
from models.db_models import Run, Source

# Setup an isolated in-memory test database with StaticPool
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_test_db():
    """Create tables before each test and drop them after for complete isolation."""
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield
    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def test_create_run_success(client):
    """Verify POST /api/runs creates a run and returns 201 with typed status."""
    payload = {
        "answer": "Python was created by Guido van Rossum and released in 1991.",
        "sources": [
            {
                "title": "Python History",
                "source_type": "text",
                "content": "Guido van Rossum began implementing Python in December 1989. It was first released in 1991.",
            }
        ],
    }

    response = client.post("/api/runs", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert "run_id" in data
    assert data["status"] == "pending"
    assert data["current_stage"] == "awaiting_verification_engine"
    assert "created_at" in data

    # Verify database persistence
    db = TestingSessionLocal()
    run = db.query(Run).filter(Run.id == data["run_id"]).first()
    assert run is not None
    assert run.original_answer == payload["answer"]
    assert len(run.sources) == 1

    source = run.sources[0]
    assert source.title == "Python History"
    assert source.source_type == "text"
    assert source.content_length == len(payload["sources"][0]["content"])
    expected_hash = hashlib.sha256(payload["sources"][0]["content"].encode("utf-8")).hexdigest()
    assert source.content_hash == expected_hash
    assert source.processing_status == "pending"
    db.close()


def test_create_run_preserves_original_answer_exactly(client):
    """Verify answer with formatting, line breaks, and whitespace is preserved unaltered."""
    verbatim_answer = "  Line 1: Special symbols @#$%^&*()\nLine 2: Tab\tIndented text.  "
    payload = {
        "answer": verbatim_answer,
        "sources": [
            {
                "title": "Reference",
                "source_type": "text",
                "content": "Reference document content.",
            }
        ],
    }

    response = client.post("/api/runs", json=payload)
    assert response.status_code == 201
    run_id = response.json()["run_id"]

    db = TestingSessionLocal()
    run = db.query(Run).filter(Run.id == run_id).first()
    assert run.original_answer == verbatim_answer
    db.close()


def test_reject_unsupported_pdf_source(client):
    """Verify PDF submissions are rejected with clear error in Phase 1."""
    payload = {
        "answer": "Valid answer text to verify.",
        "sources": [
            {
                "title": "Documentation.pdf",
                "source_type": "pdf",
                "content": "Some extracted text",
            }
        ],
    }
    response = client.post("/api/runs", json=payload)
    assert response.status_code == 400
    assert "PDF sources must be uploaded via the dedicated multipart upload endpoints" in response.json()["detail"]


def test_reject_ssrf_url_source(client):
    """Verify private/loopback URL sources are rejected by SSRF guardrails."""
    payload = {
        "answer": "Valid answer text to verify.",
        "sources": [
            {
                "title": "Local Doc",
                "source_type": "url",
                "url": "http://127.0.0.1:8000/secret",
            }
        ],
    }
    response = client.post("/api/runs", json=payload)
    assert response.status_code == 400
    assert "Access to private or local network IP addresses is forbidden" in response.json()["detail"]


def test_reject_empty_source_content(client):
    """Verify text sources with empty content are rejected."""
    payload = {
        "answer": "Valid answer text to verify.",
        "sources": [
            {
                "title": "Empty Doc",
                "source_type": "text",
                "content": "   ",
            }
        ],
    }
    response = client.post("/api/runs", json=payload)
    assert response.status_code == 400
    assert "must contain non-empty text content" in response.json()["detail"]


def test_reject_whitespace_answer(client):
    """Verify whitespace-only answer is rejected."""
    payload = {
        "answer": "     ",
        "sources": [
            {
                "title": "Valid Doc",
                "source_type": "text",
                "content": "Valid content.",
            }
        ],
    }
    response = client.post("/api/runs", json=payload)
    assert response.status_code == 400
    assert "at least 5 non-whitespace characters" in response.json()["detail"]


def test_get_run_status_success(client):
    """Verify GET /api/runs/{run_id}/status retrieves correct lifecycle status."""
    create_resp = client.post(
        "/api/runs",
        json={
            "answer": "Checking factual accuracy of model response.",
            "sources": [{"title": "Source 1", "source_type": "text", "content": "Text 1"}],
        },
    )
    run_id = create_resp.json()["run_id"]

    status_resp = client.get(f"/api/runs/{run_id}/status")
    assert status_resp.status_code == 200
    data = status_resp.json()
    assert data["run_id"] == run_id
    assert data["status"] == "pending"
    assert data["current_stage"] == "awaiting_verification_engine"


def test_get_run_status_404(client):
    """Verify GET /api/runs/{run_id}/status returns 404 for nonexistent run."""
    response = client.get("/api/runs/nonexistent-uuid-123/status")
    assert response.status_code == 404
    assert "was not found" in response.json()["detail"]


def test_get_run_report_honesty_and_empty_claims(client):
    """Verify GET /api/runs/{run_id}/report returns unassessed report without fake verdicts."""
    create_resp = client.post(
        "/api/runs",
        json={
            "answer": "This answer has not yet been verified.",
            "sources": [{"title": "Doc A", "source_type": "text", "content": "Source text."}],
        },
    )
    run_id = create_resp.json()["run_id"]

    report_resp = client.get(f"/api/runs/{run_id}/report")
    assert report_resp.status_code == 200
    data = report_resp.json()

    assert data["run_id"] == run_id
    assert data["status"] == "pending"
    assert data["original_answer"] == "This answer has not yet been verified."
    # Verification engine has not run: claims and evidence MUST be empty
    assert data["claims"] == []
    assert data["quote_audits"] == []
    assert len(data["sources"]) == 1
    assert data["sources"][0]["title"] == "Doc A"
    assert data["summary"]["total_claims"] == 0
    assert data["summary"]["supported"] == 0
    assert data["summary"]["contradicted"] == 0
    assert data["summary"]["insufficiently_supported"] == 0
    assert "No claims extracted yet" in data["summary"]["coverage_note"]


def test_get_run_report_404(client):
    """Verify GET /api/runs/{run_id}/report returns 404 for nonexistent run."""
    response = client.get("/api/runs/nonexistent-uuid-123/report")
    assert response.status_code == 404
    assert "was not found" in response.json()["detail"]
