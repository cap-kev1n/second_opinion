"""Deterministic offline tests for Phase 3: Source Passage Chunking & Evidence Retrieval."""

import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from main import app
from models.db_models import Run, Source, Claim, SourceChunk, Evidence
from models.schemas import RunStatus, AssessmentStatus
from services.chunker import chunk_source_text, TextChunk
from services.retrieval import BM25Retriever, tokenize
from config import Settings

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


# ==============================================================================
# 1. Chunker Unit Tests
# ==============================================================================

def test_chunker_exact_substring_preservation_and_offsets():
    """Verify that source_text[c.start_offset:c.end_offset] == c.content for all chunks."""
    source_text = (
        "Albert Einstein published four groundbreaking papers in 1905. "
        "These papers revolutionized modern physics and covered the photoelectric effect, "
        "Brownian motion, special relativity, and mass-energy equivalence. "
        "In 1921, he was awarded the Nobel Prize in Physics for his discovery of the photoelectric effect."
    )
    chunks = chunk_source_text(source_text, chunk_size=120, chunk_overlap=30)
    assert len(chunks) > 1

    for c in chunks:
        # Invariant check
        assert source_text[c.start_offset : c.end_offset] == c.content
        assert len(c.content) <= 120
        assert c.end_offset > c.start_offset

    # Check that overlap exists between consecutive chunks
    for i in range(len(chunks) - 1):
        assert chunks[i + 1].start_offset < chunks[i].end_offset


def test_chunker_handles_unicode_and_special_characters():
    """Verify chunking works seamlessly with Unicode, accents, and non-ASCII scripts."""
    unicode_text = "🌍 日本語テスト。La physique quantique est fascinante! Résumé des propriétés: 100°C et 42 kg."
    chunks = chunk_source_text(unicode_text, chunk_size=40, chunk_overlap=10)
    assert len(chunks) >= 2

    for c in chunks:
        assert unicode_text[c.start_offset : c.end_offset] == c.content


def test_chunker_empty_and_whitespace_sources():
    """Verify that empty and whitespace-only text return an empty chunk list."""
    assert chunk_source_text("") == []
    assert chunk_source_text("   \n\t  ") == []


def test_chunker_short_text_fits_in_single_chunk():
    """Verify that text shorter than chunk_size produces exactly one chunk."""
    text = "Short sentence."
    chunks = chunk_source_text(text, chunk_size=100, chunk_overlap=20)
    assert len(chunks) == 1
    assert chunks[0].start_offset == 0
    assert chunks[0].end_offset == len(text)
    assert chunks[0].content == text


def test_chunker_text_without_spaces_fallback():
    """Verify that unbroken text without spaces falls back safely to hard chunk_size boundary."""
    unbroken_text = "A" * 300
    chunks = chunk_source_text(unbroken_text, chunk_size=100, chunk_overlap=20)
    assert len(chunks) >= 3
    for c in chunks:
        assert unbroken_text[c.start_offset : c.end_offset] == c.content
        assert len(c.content) <= 100


def test_chunker_invalid_arguments_raise_value_error():
    """Verify chunk_size and chunk_overlap validation."""
    with pytest.raises(ValueError):
        chunk_source_text("Test", chunk_size=0)
    with pytest.raises(ValueError):
        chunk_source_text("Test", chunk_size=50, chunk_overlap=50)  # overlap >= chunk_size
    with pytest.raises(ValueError):
        chunk_source_text("Test", chunk_size=50, chunk_overlap=-5)


# ==============================================================================
# 2. BM25 Retrieval Unit Tests
# ==============================================================================

def test_bm25_ranking_relevant_vs_irrelevant():
    """Verify that passages matching query terms rank higher than irrelevant passages."""
    docs = [
        {
            "chunk_id": "c1",
            "source_id": "s1",
            "source_title": "Biology",
            "content": "Photosynthesis is the process by which green plants convert sunlight into chemical energy.",
            "start_offset": 0,
            "end_offset": 80,
            "chunk_index": 0,
        },
        {
            "chunk_id": "c2",
            "source_id": "s2",
            "source_title": "Astronomy",
            "content": "Jupiter is the largest planet in our solar system, with a prominent Great Red Spot.",
            "start_offset": 0,
            "end_offset": 80,
            "chunk_index": 0,
        },
    ]

    retriever = BM25Retriever(docs)
    results = retriever.retrieve("How do green plants produce chemical energy through photosynthesis?")
    assert len(results) > 0
    assert results[0].chunk_id == "c1"
    assert results[0].source_title == "Biology"
    assert results[0].relevance_score > 0.0


def test_bm25_claims_with_no_lexical_matches():
    """Verify that a claim with zero vocabulary overlap returns an empty list, not false."""
    docs = [
        {
            "chunk_id": "c1",
            "source_id": "s1",
            "source_title": "Cooking",
            "content": "Baking bread requires flour, water, salt, and yeast.",
            "start_offset": 0,
            "end_offset": 50,
            "chunk_index": 0,
        }
    ]
    retriever = BM25Retriever(docs)
    results = retriever.retrieve("Quantum computing uses qubits and superposition.")
    assert results == []


def test_bm25_deterministic_tie_breaking():
    """Verify deterministic tie-breaking by start_offset when scores are identical."""
    docs = [
        {
            "chunk_id": "chunk-b",
            "source_id": "s1",
            "source_title": "Doc",
            "content": "Apple banana fruit salad.",
            "start_offset": 50,
            "end_offset": 75,
            "chunk_index": 1,
        },
        {
            "chunk_id": "chunk-a",
            "source_id": "s1",
            "source_title": "Doc",
            "content": "Apple banana fruit salad.",
            "start_offset": 0,
            "end_offset": 25,
            "chunk_index": 0,
        },
    ]
    retriever = BM25Retriever(docs)
    results = retriever.retrieve("Apple banana")
    assert len(results) == 2
    # Equal BM25 score, earlier offset (0) must break the tie first
    assert results[0].chunk_id == "chunk-a"
    assert results[0].start_offset == 0
    assert results[1].chunk_id == "chunk-b"
    assert results[1].start_offset == 50


# ==============================================================================
# 3. End-to-End API and Integration Tests
# ==============================================================================

def test_retrieval_endpoint_success_and_verdicts_remain_null(client):
    """Verify POST /api/runs/{run_id}/retrieve succeeds, attaches candidate evidence, and verdicts remain NULL."""
    # 1. Create run
    create_resp = client.post(
        "/api/runs",
        json={
            "answer": "Water boils at 100 degrees Celsius. The Eiffel Tower is in Paris.",
            "sources": [
                {
                    "title": "Thermodynamics Guide",
                    "source_type": "text",
                    "content": "Water boils at 100 degrees Celsius at standard atmospheric pressure of 1 atm.",
                },
                {
                    "title": "European Landmarks",
                    "source_type": "text",
                    "content": "The Eiffel Tower is a wrought-iron lattice tower located on the Champ de Mars in Paris, France.",
                },
            ],
        },
    )
    assert create_resp.status_code == 201
    run_id = create_resp.json()["run_id"]

    # Seed extracted claims manually into the DB to simulate successful Phase 2 extraction
    db = TestingSessionLocal()
    c1 = Claim(
        run_id=run_id,
        original_text="Water boils at 100 degrees Celsius",
        normalized_text="Water boils at 100 degrees Celsius.",
        position_in_answer=0,
        verdict=None,
        assessment_status=AssessmentStatus.PENDING.value,
    )
    c2 = Claim(
        run_id=run_id,
        original_text="The Eiffel Tower is in Paris",
        normalized_text="The Eiffel Tower is located in Paris.",
        position_in_answer=36,
        verdict=None,
        assessment_status=AssessmentStatus.PENDING.value,
    )
    db.add_all([c1, c2])
    run_obj = db.query(Run).filter(Run.id == run_id).first()
    run_obj.status = RunStatus.PROCESSING.value
    run_obj.current_stage = "awaiting_evidence"  # Phase 2 complete
    db.commit()
    db.close()

    # 2. Trigger Phase 3 retrieval
    ret_resp = client.post(f"/api/runs/{run_id}/retrieve")
    assert ret_resp.status_code == 200
    report = ret_resp.json()

    # Verify lifecycle stage transition
    assert report["status"] == "processing"
    assert len(report["claims"]) == 2

    # Check Claim 1 evidence
    claim1 = report["claims"][0]
    assert len(claim1["evidence"]) > 0
    assert claim1["evidence"][0]["source_title"] == "Thermodynamics Guide"
    assert "100 degrees Celsius" in claim1["evidence"][0]["excerpt"]
    assert claim1["evidence"][0]["relationship"] == "candidate"
    assert claim1["evidence"][0]["relevance_score"] > 0.0
    # CRITICAL INVARIANT: Verdict must remain None!
    assert claim1["verdict"] is None
    assert claim1["assessment_status"] == "pending"

    # Check Claim 2 evidence
    claim2 = report["claims"][1]
    assert len(claim2["evidence"]) > 0
    assert claim2["evidence"][0]["source_title"] == "European Landmarks"
    assert "Paris" in claim2["evidence"][0]["excerpt"]
    assert claim2["evidence"][0]["relationship"] == "candidate"
    assert claim2["verdict"] is None
    assert claim2["assessment_status"] == "pending"

    # Status endpoint agrees
    st_resp = client.get(f"/api/runs/{run_id}/status")
    assert st_resp.json()["current_stage"] == "awaiting_assessment"


def test_retrieval_cross_run_isolation(client):
    """Verify that a run NEVER retrieves chunks from another run's sources."""
    # Create Run A with Source A
    rA = client.post(
        "/api/runs",
        json={
            "answer": "Quantum mechanics describes microscopic particles.",
            "sources": [{"title": "Source A", "source_type": "text", "content": "Quantum mechanics describes microscopic particles."}],
        },
    ).json()["run_id"]

    # Create Run B with Source B
    rB = client.post(
        "/api/runs",
        json={
            "answer": "Quantum mechanics describes microscopic particles.",
            "sources": [{"title": "Source B", "source_type": "text", "content": "Cooking recipes for Italian pasta and pizza."}],
        },
    ).json()["run_id"]

    # Setup extracted claim on Run B
    db = TestingSessionLocal()
    cB = Claim(
        run_id=rB,
        original_text="Quantum mechanics describes microscopic particles.",
        normalized_text="Quantum mechanics describes microscopic particles.",
        position_in_answer=0,
        verdict=None,
        assessment_status=AssessmentStatus.PENDING.value,
    )
    db.add(cB)
    runB = db.query(Run).filter(Run.id == rB).first()
    runB.status = RunStatus.PROCESSING.value
    runB.current_stage = "awaiting_evidence"
    db.commit()
    db.close()

    # Trigger retrieval on Run B
    ret_resp = client.post(f"/api/runs/{rB}/retrieve")
    assert ret_resp.status_code == 200
    reportB = ret_resp.json()

    # Run B has only cooking sources: it must NOT retrieve chunks from Run A's quantum source!
    assert len(reportB["claims"]) == 1
    assert reportB["claims"][0]["evidence"] == []  # No matches in Run B's sources!


def test_retrieval_rejected_before_extraction(client):
    """Verify that POST /api/runs/{run_id}/retrieve returns 400 if extraction has not completed."""
    create_resp = client.post(
        "/api/runs",
        json={
            "answer": "Some answer text.",
            "sources": [{"title": "Doc", "source_type": "text", "content": "Text"}],
        },
    )
    run_id = create_resp.json()["run_id"]

    # Attempt retrieval before extraction
    ret_resp = client.post(f"/api/runs/{run_id}/retrieve")
    assert ret_resp.status_code == 400
    assert "Claim extraction must be completed" in ret_resp.json()["detail"]


def test_retrieval_idempotency_on_repeated_calls(client):
    """Verify that calling retrieve multiple times is safe and deterministic."""
    create_resp = client.post(
        "/api/runs",
        json={
            "answer": "Python was released in 1991.",
            "sources": [{"title": "Python History", "source_type": "text", "content": "Python was released in 1991 by Guido."}],
        },
    )
    run_id = create_resp.json()["run_id"]

    db = TestingSessionLocal()
    claim = Claim(
        run_id=run_id,
        original_text="Python was released in 1991",
        normalized_text="Python was released in 1991.",
        position_in_answer=0,
        verdict=None,
        assessment_status=AssessmentStatus.PENDING.value,
    )
    db.add(claim)
    r = db.query(Run).filter(Run.id == run_id).first()
    r.status = RunStatus.PROCESSING.value
    r.current_stage = "awaiting_evidence"
    db.commit()
    db.close()

    # Call 1
    resp1 = client.post(f"/api/runs/{run_id}/retrieve")
    assert resp1.status_code == 200
    ev1 = resp1.json()["claims"][0]["evidence"]
    assert len(ev1) > 0

    # Call 2
    resp2 = client.post(f"/api/runs/{run_id}/retrieve")
    assert resp2.status_code == 200
    ev2 = resp2.json()["claims"][0]["evidence"]
    assert len(ev2) == len(ev1)
    assert ev2[0]["excerpt"] == ev1[0]["excerpt"]

    # Ensure no duplicate chunk records were accumulated in DB
    db = TestingSessionLocal()
    chunk_count = db.query(SourceChunk).join(Source).filter(Source.run_id == run_id).count()
    assert chunk_count == 1
    db.close()


def test_retrieval_handles_zero_claims_and_empty_sources(client):
    """Verify that runs with 0 claims or empty sources retrieve safely without crashing."""
    create_resp = client.post(
        "/api/runs",
        json={
            "answer": "What a beautiful day!",
            "sources": [{"title": "Doc", "source_type": "text", "content": "General text."}],
        },
    )
    run_id = create_resp.json()["run_id"]

    db = TestingSessionLocal()
    r = db.query(Run).filter(Run.id == run_id).first()
    r.status = RunStatus.PROCESSING.value
    r.current_stage = "awaiting_evidence"
    # Zero claims persisted (e.g. opinion-only answer)
    db.commit()
    db.close()

    resp = client.post(f"/api/runs/{run_id}/retrieve")
    assert resp.status_code == 200
    report = resp.json()
    assert report["claims"] == []
    assert report["status"] == "processing"


def test_get_endpoints_do_not_trigger_retrieval(client):
    """Verify that calling GET endpoints does not trigger retrieval or modify evidence."""
    create_resp = client.post(
        "/api/runs",
        json={
            "answer": "Some answer text.",
            "sources": [{"title": "Doc", "source_type": "text", "content": "Text"}],
        },
    )
    run_id = create_resp.json()["run_id"]

    client.get(f"/api/runs/{run_id}/status")
    client.get(f"/api/runs/{run_id}/report")
    client.get(f"/api/runs/{run_id}/claims")

    db = TestingSessionLocal()
    evidence_count = db.query(Evidence).count()
    chunk_count = db.query(SourceChunk).count()
    db.close()

    assert evidence_count == 0
    assert chunk_count == 0


def test_invalid_settings_boundary_fails_safely():
    """Verify that invalid chunking and retrieval settings trigger validation errors."""
    with pytest.raises(ValidationError):
        # chunk_size_chars must be >= 100
        Settings(chunk_size_chars=50)

    with pytest.raises(ValidationError):
        # chunk_overlap_chars must be < chunk_size_chars
        Settings(chunk_size_chars=200, chunk_overlap_chars=250)

    with pytest.raises(ValidationError):
        # retrieval_top_k must be >= 1
        Settings(retrieval_top_k=0)


def test_bm25_top_k_zero_or_negative():
    """Verify that retrieve with top_k <= 0 returns an empty list, not a sliced list."""
    docs = [
        {
            "chunk_id": "c1",
            "source_id": "s1",
            "source_title": "Doc",
            "content": "Python is a high-level programming language.",
            "start_offset": 0,
            "end_offset": 43,
            "chunk_index": 0,
        }
    ]
    retriever = BM25Retriever(docs)
    assert retriever.retrieve("Python programming", top_k=0) == []
    assert retriever.retrieve("Python programming", top_k=-1) == []
    assert retriever.retrieve("Python programming", top_k=-5) == []


def test_bm25_heavily_overlapping_chunks_deduplication():
    """Verify that chunks from the same source with >= 50% overlap are deduplicated in top-k."""
    docs = [
        {
            "chunk_id": "chunk-1",
            "source_id": "src-1",
            "source_title": "Source 1",
            "content": "Quantum mechanics explains the behavior of subatomic particles.",
            "start_offset": 0,
            "end_offset": 63,
            "chunk_index": 0,
        },
        {
            "chunk_id": "chunk-2",
            "source_id": "src-1",
            "source_title": "Source 1",
            # Overlaps 80%+ with chunk-1 (start 10, end 63 is 53 chars out of 63)
            "content": "mechanics explains the behavior of subatomic particles in physics.",
            "start_offset": 8,
            "end_offset": 74,
            "chunk_index": 1,
        },
        {
            "chunk_id": "chunk-3",
            "source_id": "src-2",
            "source_title": "Source 2",
            "content": "Subatomic particles behave according to quantum probability.",
            "start_offset": 0,
            "end_offset": 60,
            "chunk_index": 0,
        },
    ]
    retriever = BM25Retriever(docs)
    results = retriever.retrieve("Quantum mechanics subatomic particles", top_k=3)

    # Both chunk-1 and chunk-2 match, but since they heavily overlap on src-1,
    # the second overlapping chunk is skipped so that chunk-3 from src-2 is included!
    returned_ids = [r.chunk_id for r in results]
    assert len(results) == 2
    assert "chunk-1" in returned_ids
    assert "chunk-3" in returned_ids
    assert "chunk-2" not in returned_ids


def test_retrieval_reprocessing_safe_deletion_order(client):
    """Verify that repeated evidence retrieval handles deletions cleanly in reverse dependency order."""
    create_resp = client.post(
        "/api/runs",
        json={
            "answer": "Mars has two moons named Phobos and Deimos.",
            "sources": [{"title": "Mars Astronomy", "source_type": "text", "content": "Mars has two moons, Phobos and Deimos, discovered in 1877."}],
        },
    )
    run_id = create_resp.json()["run_id"]

    db = TestingSessionLocal()
    claim = Claim(
        run_id=run_id,
        original_text="Mars has two moons named Phobos and Deimos",
        normalized_text="Mars has two moons named Phobos and Deimos.",
        position_in_answer=0,
        verdict=None,
        assessment_status=AssessmentStatus.PENDING.value,
    )
    db.add(claim)
    r = db.query(Run).filter(Run.id == run_id).first()
    r.status = RunStatus.PROCESSING.value
    r.current_stage = "awaiting_evidence"
    db.commit()
    db.close()

    # Pass 1
    resp1 = client.post(f"/api/runs/{run_id}/retrieve")
    assert resp1.status_code == 200

    # Pass 2: triggers deletion of prior evidence then prior chunks
    resp2 = client.post(f"/api/runs/{run_id}/retrieve")
    assert resp2.status_code == 200
    report = resp2.json()

    # Verify everything remains intact and correctly populated
    assert len(report["claims"]) == 1
    assert len(report["claims"][0]["evidence"]) > 0
    assert report["claims"][0]["verdict"] is None
    assert report["claims"][0]["assessment_status"] == "pending"
