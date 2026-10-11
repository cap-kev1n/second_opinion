"""Comprehensive tests for factual claim extraction and Phase 1 corrections."""

from unittest.mock import AsyncMock, patch, MagicMock
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from main import app
from models.db_models import Run, Source, Claim
from prompts.claim_extraction import ExtractedClaimItem, ClaimExtractionResult
from services.llm_client import BaseLLMClient, GeminiLLMClient

# Isolated in-memory test database with StaticPool
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_test_db():
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


class MockLLMClient(BaseLLMClient):
    """Deterministic mock client for testing claim extraction offline."""

    def __init__(self, claims=None, error=None):
        self._claims = claims if claims is not None else []
        self._error = error
        self.call_count = 0

    def is_configured(self) -> bool:
        return True

    async def extract_claims(self, answer_text: str):
        self.call_count += 1
        if self._error:
            raise self._error
        return self._claims

    async def assess_claim(self, claim_text: str, evidence_passages):
        raise NotImplementedError()


# ==============================================================================
# Phase 1 Corrections: Source Content Retrieval Tests
# ==============================================================================

def test_source_content_retrieval_success(client):
    """Verify GET /api/runs/{run_id}/sources/{source_id} returns exact stored text."""
    create_resp = client.post(
        "/api/runs",
        json={
            "answer": "Python was created by Guido van Rossum in 1991.",
            "sources": [
                {
                    "title": "Exact Python Docs",
                    "source_type": "text",
                    "content": "Line 1: Special characters !@#$%^&*()\nLine 2: Indented text.",
                }
            ],
        },
    )
    assert create_resp.status_code == 201
    run_id = create_resp.json()["run_id"]

    # Get report to find source ID
    rep_resp = client.get(f"/api/runs/{run_id}/report")
    assert rep_resp.status_code == 200
    source_id = rep_resp.json()["sources"][0]["id"]

    # Fetch exact source content
    src_resp = client.get(f"/api/runs/{run_id}/sources/{source_id}")
    assert src_resp.status_code == 200
    src_data = src_resp.json()
    assert src_data["id"] == source_id
    assert src_data["title"] == "Exact Python Docs"
    assert src_data["content"] == "Line 1: Special characters !@#$%^&*()\nLine 2: Indented text."
    assert src_data["content_length"] == len("Line 1: Special characters !@#$%^&*()\nLine 2: Indented text.")


def test_source_content_404_for_unknown_source_or_run(client):
    """Verify 404 is returned when run or source ID does not exist."""
    # Unknown run
    resp = client.get("/api/runs/nonexistent-run/sources/nonexistent-source")
    assert resp.status_code == 404

    # Valid run but unknown source
    create_resp = client.post(
        "/api/runs",
        json={
            "answer": "Answer text here.",
            "sources": [{"title": "Doc", "source_type": "text", "content": "Text"}],
        },
    )
    run_id = create_resp.json()["run_id"]
    resp2 = client.get(f"/api/runs/{run_id}/sources/unknown-src-id")
    assert resp2.status_code == 404


# ==============================================================================
# Phase 2: Claim Extraction Tests
# ==============================================================================

def test_extract_claims_normal_answer_success(client):
    """Verify extracting multiple atomic factual claims from an answer."""
    create_resp = client.post(
        "/api/runs",
        json={
            "answer": "Python was created by Guido van Rossum in 1991. It emphasizes readability.",
            "sources": [{"title": "Doc", "source_type": "text", "content": "Text"}],
        },
    )
    run_id = create_resp.json()["run_id"]

    mock_claims = [
        {
            "original_text": "Python was created by Guido van Rossum in 1991",
            "normalized_text": "Python was created by Guido van Rossum in 1991.",
        },
        {
            "original_text": "It emphasizes readability",
            "normalized_text": "Python emphasizes code readability.",
        },
    ]

    mock_client = MockLLMClient(claims=mock_claims)

    with patch("services.claim_extractor.llm_service", mock_client):
        extract_resp = client.post(f"/api/runs/{run_id}/extract")
        assert extract_resp.status_code == 200
        report = extract_resp.json()

        assert report["status"] == "processing"
        assert len(report["claims"]) == 2
        assert report["summary"]["total_claims"] == 2
        assert "awaiting evidence" in report["summary"]["coverage_note"].lower()

        # Check claim 1
        c1 = report["claims"][0]
        assert c1["original_text"] == "Python was created by Guido van Rossum in 1991"
        assert c1["normalized_text"] == "Python was created by Guido van Rossum in 1991."
        assert c1["verdict"] is None  # CRITICAL: Not yet assessed
        assert c1["assessment_status"] == "pending"
        assert c1["evidence"] == []

        # Verify database records
        db = TestingSessionLocal()
        claims_in_db = db.query(Claim).filter(Claim.run_id == run_id).all()
        assert len(claims_in_db) == 2
        assert claims_in_db[0].run_id == run_id
        assert claims_in_db[0].verdict is None
        db.close()


def test_compound_statement_splitting_and_order_preservation(client):
    """Verify compound statements split into atomic claims preserve sequence."""
    create_resp = client.post(
        "/api/runs",
        json={
            "answer": "Tesla was founded in 2003 and is headquartered in Austin, Texas.",
            "sources": [{"title": "Doc", "source_type": "text", "content": "Text"}],
        },
    )
    run_id = create_resp.json()["run_id"]

    mock_claims = [
        {"original_text": "Tesla was founded in 2003", "normalized_text": "Tesla was founded in 2003."},
        {"original_text": "headquartered in Austin, Texas", "normalized_text": "Tesla is headquartered in Austin, Texas."},
    ]

    mock_client = MockLLMClient(claims=mock_claims)

    with patch("services.claim_extractor.llm_service", mock_client):
        extract_resp = client.post(f"/api/runs/{run_id}/extract")
        assert extract_resp.status_code == 200
        claims = extract_resp.json()["claims"]

        assert len(claims) == 2
        assert claims[0]["original_text"] == "Tesla was founded in 2003"
        assert claims[1]["original_text"] == "headquartered in Austin, Texas"


def test_opinion_or_non_factual_answer_returns_empty_claims(client):
    """Verify answers with pure opinion return an empty claim list successfully."""
    create_resp = client.post(
        "/api/runs",
        json={
            "answer": "In my opinion, this phone feels great to hold and has a wonderful color.",
            "sources": [{"title": "Doc", "source_type": "text", "content": "Text"}],
        },
    )
    run_id = create_resp.json()["run_id"]

    mock_client = MockLLMClient(claims=[])  # Empty claims list from Gemini

    with patch("services.claim_extractor.llm_service", mock_client):
        extract_resp = client.post(f"/api/runs/{run_id}/extract")
        assert extract_resp.status_code == 200
        report = extract_resp.json()

        # Zero claims is a successful extraction, NOT an error
        assert report["claims"] == []
        assert report["summary"]["total_claims"] == 0
        assert report["status"] == "processing"

        # Status endpoint agrees
        st_resp = client.get(f"/api/runs/{run_id}/status")
        assert st_resp.json()["current_stage"] == "awaiting_evidence"


def test_extraction_failure_updates_run_to_failed(client):
    """Verify that a provider error sets status to failed and does not fabricate claims."""
    create_resp = client.post(
        "/api/runs",
        json={
            "answer": "Some answer to verify.",
            "sources": [{"title": "Doc", "source_type": "text", "content": "Text"}],
        },
    )
    run_id = create_resp.json()["run_id"]

    mock_client = MockLLMClient(error=RuntimeError("Simulated Gemini API 503 Unavailable"))

    with patch("services.claim_extractor.llm_service", mock_client):
        extract_resp = client.post(f"/api/runs/{run_id}/extract")
        assert extract_resp.status_code == 502

        # Check status endpoint reflects failure
        st_resp = client.get(f"/api/runs/{run_id}/status")
        assert st_resp.status_code == 200
        data = st_resp.json()
        assert data["status"] == "failed"
        assert data["current_stage"] == "failed"
        assert "Simulated Gemini API 503" in data["error_message"]

        # Check report endpoint agrees
        rep_resp = client.get(f"/api/runs/{run_id}/report")
        assert rep_resp.status_code == 200
        rep_data = rep_resp.json()
        assert rep_data["status"] == "failed"
        assert rep_data["claims"] == []  # No fabricated claims!


def test_idempotent_extraction_avoids_duplicate_calls(client):
    """Verify that calling extract on an already completed extraction returns existing claims."""
    create_resp = client.post(
        "/api/runs",
        json={
            "answer": "Python was created in 1991.",
            "sources": [{"title": "Doc", "source_type": "text", "content": "Text"}],
        },
    )
    run_id = create_resp.json()["run_id"]

    mock_client = MockLLMClient(claims=[{"original_text": "Python was created in 1991", "normalized_text": "Python was created in 1991."}])

    with patch("services.claim_extractor.llm_service", mock_client):
        # Call 1
        resp1 = client.post(f"/api/runs/{run_id}/extract")
        assert resp1.status_code == 200
        assert mock_client.call_count == 1

        # Call 2
        resp2 = client.post(f"/api/runs/{run_id}/extract")
        assert resp2.status_code == 200
        # Call count must remain 1 because it was idempotent!
        assert mock_client.call_count == 1


def test_concurrent_extraction_returns_409_conflict(client):
    """Verify that calling extraction while a run is currently extracting returns 409 Conflict."""
    db = TestingSessionLocal()
    run = Run(
        original_answer="Answer in progress.",
        status="processing",
        current_stage="extracting_claims",  # Currently running
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    run_id = run.id
    db.close()

    resp = client.post(f"/api/runs/{run_id}/extract")
    assert resp.status_code == 409
    assert "already in progress" in resp.json()["detail"]


def test_get_endpoints_do_not_trigger_gemini(client):
    """Verify that calling GET endpoints never triggers Gemini calls."""
    create_resp = client.post(
        "/api/runs",
        json={
            "answer": "Python was created in 1991.",
            "sources": [{"title": "Doc", "source_type": "text", "content": "Text"}],
        },
    )
    run_id = create_resp.json()["run_id"]

    mock_client = MockLLMClient(claims=[])

    with patch("services.llm_client.llm_service", mock_client):
        # Call GET status
        client.get(f"/api/runs/{run_id}/status")
        # Call GET report
        client.get(f"/api/runs/{run_id}/report")
        # Call GET claims
        client.get(f"/api/runs/{run_id}/claims")

        assert mock_client.call_count == 0


def test_unconfigured_api_key_raises_configuration_error():
    """Verify that GeminiLLMClient raises clear error when API key is missing."""
    client = GeminiLLMClient(api_key="")
    assert not client.is_configured()

    with pytest.raises(RuntimeError, match="Gemini API key is not configured"):
        client._get_client()


def test_extracted_claim_schema_validation():
    """Verify that ExtractedClaimItem and ClaimExtractionResult enforce valid structures."""
    # Valid item
    item = ExtractedClaimItem(original_text="Earth orbits Sun", normalized_text="The Earth orbits the Sun.")
    assert item.original_text == "Earth orbits Sun"

    # Missing original_text
    with pytest.raises(ValidationError):
        ExtractedClaimItem(normalized_text="Valid text")

    # Empty claim list is valid
    res = ClaimExtractionResult(claims=[])
    assert res.claims == []


def test_gemini_client_handles_malformed_json():
    """Verify that GeminiLLMClient catches malformed JSON from provider and raises RuntimeError."""
    import asyncio

    async def _test():
        client = GeminiLLMClient(api_key="valid_dummy_key_for_test")
        client._client = MagicMock()

        mock_response = MagicMock()
        mock_response.text = "{ not valid json at all }"

        client._client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        with pytest.raises(RuntimeError, match="Claim extraction failed after 2 attempts"):
            await client.extract_claims("Sample answer")

    asyncio.run(_test())


def test_gemini_client_handles_timeout():
    """Verify that provider timeouts are caught and converted to sanitized errors."""
    import asyncio

    async def _test():
        client = GeminiLLMClient(api_key="valid_dummy_key_for_test")
        client._client = MagicMock()

        client._client.aio.models.generate_content = AsyncMock(side_effect=asyncio.TimeoutError("Request timed out"))

        with pytest.raises(RuntimeError, match="Claim extraction failed after 2 attempts"):
            await client.extract_claims("Sample answer")

    asyncio.run(_test())


def test_source_content_isolated_to_its_own_run(client):
    """Verify that a source cannot be accessed using an unrelated run_id."""
    r1 = client.post(
        "/api/runs",
        json={"answer": "First answer text.", "sources": [{"title": "Doc 1", "source_type": "text", "content": "Content 1"}]},
    )
    r2 = client.post(
        "/api/runs",
        json={"answer": "Second answer text.", "sources": [{"title": "Doc 2", "source_type": "text", "content": "Content 2"}]},
    )
    run1_id = r1.json()["run_id"]
    run2_id = r2.json()["run_id"]

    source1_id = client.get(f"/api/runs/{run1_id}/report").json()["sources"][0]["id"]
    source2_id = client.get(f"/api/runs/{run2_id}/report").json()["sources"][0]["id"]

    # Accessing Source 1 with Run 2 must return 404
    cross_resp = client.get(f"/api/runs/{run2_id}/sources/{source1_id}")
    assert cross_resp.status_code == 404

    # Accessing Source 2 with Run 1 must return 404
    cross_resp2 = client.get(f"/api/runs/{run1_id}/sources/{source2_id}")
    assert cross_resp2.status_code == 404

    # Proper access succeeds
    valid_resp = client.get(f"/api/runs/{run1_id}/sources/{source1_id}")
    assert valid_resp.status_code == 200
    assert valid_resp.json()["content"] == "Content 1"


def test_idempotent_extraction_on_zero_claims_avoids_duplicate_calls(client):
    """Verify that an answer with zero claims is also protected by idempotency."""
    create_resp = client.post(
        "/api/runs",
        json={
            "answer": "What is the meaning of life? Is it 42?",
            "sources": [{"title": "Doc", "source_type": "text", "content": "Text"}],
        },
    )
    run_id = create_resp.json()["run_id"]

    mock_client = MockLLMClient(claims=[])

    with patch("services.claim_extractor.llm_service", mock_client):
        # Call 1: returns empty claims
        resp1 = client.post(f"/api/runs/{run_id}/extract")
        assert resp1.status_code == 200
        assert resp1.json()["claims"] == []
        assert mock_client.call_count == 1

        # Call 2: idempotent, must NOT re-call Gemini
        resp2 = client.post(f"/api/runs/{run_id}/extract")
        assert resp2.status_code == 200
        assert resp2.json()["claims"] == []
        assert mock_client.call_count == 1


def test_gemini_client_timeout_configured_in_milliseconds():
    """Verify that HttpOptions timeout is configured in milliseconds (seconds * 1000)."""
    with patch("services.llm_client.settings") as mock_settings:
        mock_settings.gemini_api_key = "test_key"
        mock_settings.gemini_model = "gemini-2.5-flash"
        mock_settings.llm_timeout_seconds = 45

        client = GeminiLLMClient(api_key="test_key")
        with patch("google.genai.Client") as mock_genai_client:
            client._get_client()
            mock_genai_client.assert_called_once()
            call_kwargs = mock_genai_client.call_args[1]
            http_options = call_kwargs.get("http_options")
            assert http_options.timeout == 45000  # 45 seconds * 1000 ms
