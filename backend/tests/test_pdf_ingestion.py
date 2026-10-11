"""Comprehensive offline unit and integration tests for Phase 6 PDF Reference Ingestion

and Page-Level Evidence Attribution.
"""

import io
import json
import os
import shutil
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
import pymupdf
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from config import settings
from database import Base, get_db
from main import app
from models.db_models import Run, Source, Claim, SourceChunk, Evidence
from models.schemas import RunStatus, SourceType, Verdict, AssessmentStatus
from services.pdf_ingestion import (
    extract_and_validate_pdf,
    get_pdf_storage_dir,
    cleanup_pdf_file,
    get_pdf_page_texts,
)


# Setup isolated in-memory test database
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


def create_synthetic_pdf(pages_text: list[str], encrypt: bool = False, password: str = "secret") -> bytes:
    """Helper to generate an in-memory PDF with specified text per page."""
    doc = pymupdf.open()
    for text in pages_text:
        page = doc.new_page()
        if text.strip():
            page.insert_text((50, 72), text)

    if encrypt:
        pdf_bytes = doc.tobytes(
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            user_pw=password,
            owner_pw=password,
        )
    else:
        pdf_bytes = doc.tobytes()

    doc.close()
    return pdf_bytes


def test_pdf_extraction_multi_page_success():
    """Verify multi-page PDF text extraction with 1-based page numbers and metadata."""
    pages = [
        "Page 1: Guido van Rossum designed Python as a general-purpose programming language.",
        "Page 2: Python 2.0 introduced list comprehensions and cycle-detecting garbage collection.",
        "Page 3: Python 3.0 was released in December 2008 with unicode string defaults.",
    ]
    pdf_bytes = create_synthetic_pdf(pages)

    result = extract_and_validate_pdf(
        file_bytes=pdf_bytes,
        original_filename="python_guide.pdf",
        source_id="test-source-1",
    )

    assert result.page_count == 3
    assert result.scanned_page_count == 0
    assert result.processing_status == "success"
    assert result.failure_reason is None

    # Check concatenated content
    for page_text in pages:
        assert page_text in result.raw_content

    # Check extraction metadata: must be lightweight and NOT contain full document text
    meta = json.loads(result.extraction_metadata)
    assert meta["page_count"] == 3
    assert len(meta["pages"]) == 3
    assert meta["pages"][0]["page_number"] == 1
    assert meta["pages"][1]["page_number"] == 2
    assert meta["pages"][2]["page_number"] == 3
    assert "pages_content" not in meta  # Invariant: metadata never duplicates full document text

    # Verify safe disk storage
    storage_file = get_pdf_storage_dir() / "test-source-1.pdf"
    assert storage_file.exists()

    # Clean up test artifact
    cleanup_pdf_file("test-source-1")


def test_pdf_per_page_chunking_exact_substring_invariants(client):
    """Verify chunks never span page boundaries and page-local offsets match exactly."""
    pages = [
        "First page sentence one. First page sentence two. First page sentence three.",
        "Second page sentence one. Second page sentence two.",
    ]
    pdf_bytes = create_synthetic_pdf(pages)

    # Create run with PDF source via endpoint
    response = client.post(
        "/api/runs/upload-pdf",
        data={"answer": "First page sentence one is valid. Second page sentence two is verified."},
        files={"file": ("sample.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )
    assert response.status_code == 201
    run_id = response.json()["run_id"]

    db = TestingSessionLocal()
    # Add claims manually to test retrieval
    claim1 = Claim(
        id="c-1",
        run_id=run_id,
        original_text="First page sentence one is valid.",
        normalized_text="First page sentence one is valid.",
        position_in_answer=0,
    )
    claim2 = Claim(
        id="c-2",
        run_id=run_id,
        original_text="Second page sentence two is verified.",
        normalized_text="Second page sentence two is verified.",
        position_in_answer=1,
    )
    db.add_all([claim1, claim2])
    run = db.query(Run).filter(Run.id == run_id).first()
    run.current_stage = "awaiting_evidence"
    db.commit()

    # Trigger BM25 retrieval
    ret_resp = client.post(f"/api/runs/{run_id}/retrieve?top_k=5")
    assert ret_resp.status_code == 200

    # Inspect chunks directly in DB
    source = db.query(Source).filter(Source.run_id == run_id).first()
    chunks = db.query(SourceChunk).filter(SourceChunk.source_id == source.id).all()
    assert len(chunks) > 0

    page_records = get_pdf_page_texts(source.id, source.raw_content or "")
    pages_map = {p_num: p_text for p_num, p_text in page_records}

    for chunk in chunks:
        assert chunk.page_number in [1, 2]
        page_text = pages_map[chunk.page_number]
        # Invariant: chunk content equals page_text[start:end]
        assert page_text[chunk.start_offset:chunk.end_offset] == chunk.content
        # Invariant: chunks never cross page boundaries
        assert chunk.content in page_text

    # Inspect evidence
    evidence_items = db.query(Evidence).join(Claim).filter(Claim.run_id == run_id).all()
    for ev in evidence_items:
        assert ev.page_number in [1, 2]
        assert ev.source_location.startswith(f"Page {ev.page_number}, char ")

    db.close()


def test_pdf_empty_and_scanned_page_detection():
    """Verify empty/image-only pages are counted and flagged with OCR warnings."""
    pages = [
        "Normal text on page 1.",
        "",  # Empty scanned page
        "Normal text on page 3.",
    ]
    pdf_bytes = create_synthetic_pdf(pages)

    result = extract_and_validate_pdf(
        file_bytes=pdf_bytes,
        original_filename="mixed_scanned.pdf",
        source_id="test-source-scanned",
    )

    assert result.page_count == 3
    assert result.scanned_page_count == 1
    assert result.processing_status == "partial"
    assert "OCR" in (result.failure_reason or "")

    meta = json.loads(result.extraction_metadata)
    assert meta["scanned_page_count"] == 1
    assert any("OCR" in w for w in meta["warnings"])

    # Clean up file
    cleanup_pdf_file("test-source-scanned")


def test_pdf_completely_empty_or_scanned_rejected(client):
    """Verify PDF with no readable text on any page is rejected with 400 and OCR explanation."""
    empty_pages = ["", "   \n\t  "]
    pdf_bytes = create_synthetic_pdf(empty_pages)

    response = client.post(
        "/api/runs/upload-pdf",
        data={"answer": "Some answer that requires evidence."},
        files={"file": ("empty.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )

    assert response.status_code == 400
    assert "Optical Character Recognition (OCR) may be required" in response.json()["detail"]


def test_pdf_magic_bytes_invalid(client):
    """Verify files without %PDF- magic bytes are rejected immediately."""
    fake_pdf = b"NOT_A_PDF_DOCUMENT_CONTENT"

    response = client.post(
        "/api/runs/upload-pdf",
        data={"answer": "Some answer that requires evidence."},
        files={"file": ("fake.pdf", io.BytesIO(fake_pdf), "application/pdf")},
    )

    assert response.status_code == 400
    assert "%PDF-" in response.json()["detail"]


def test_pdf_size_limit_exceeded(client):
    """Verify files exceeding max_pdf_size_mb are rejected."""
    # Create fake oversize bytes starting with %PDF-
    oversize = b"%PDF-" + b"0" * ((settings.max_pdf_size_mb * 1024 * 1024) + 10)

    response = client.post(
        "/api/runs/upload-pdf",
        data={"answer": "Some answer that requires evidence."},
        files={"file": ("large.pdf", io.BytesIO(oversize), "application/pdf")},
    )

    assert response.status_code in [400, 413]
    assert "exceeds maximum allowed limit" in response.json()["detail"]


def test_pdf_page_limit_exceeded(client):
    """Verify PDFs with more than max_pdf_pages are rejected."""
    # Create synthetic PDF with max_pdf_pages + 1 pages
    pages = ["Page content"] * (settings.max_pdf_pages + 1)
    pdf_bytes = create_synthetic_pdf(pages)

    response = client.post(
        "/api/runs/upload-pdf",
        data={"answer": "Some answer that requires evidence."},
        files={"file": ("many_pages.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )

    assert response.status_code == 400
    assert f"maximum allowed limit of {settings.max_pdf_pages} pages" in response.json()["detail"]


def test_pdf_encrypted_rejected(client):
    """Verify password-protected / encrypted PDFs are rejected with clear message."""
    pages = ["Confidential text that should be protected."]
    encrypted_bytes = create_synthetic_pdf(pages, encrypt=True, password="mypassword")

    response = client.post(
        "/api/runs/upload-pdf",
        data={"answer": "Some answer that requires evidence."},
        files={"file": ("secret.pdf", io.BytesIO(encrypted_bytes), "application/pdf")},
    )

    assert response.status_code == 400
    assert "Encrypted or password-protected" in response.json()["detail"]


def test_pdf_corrupt_stream_rejected(client):
    """Verify corrupt PDF content is caught gracefully."""
    corrupt_bytes = b"%PDF-1.7\nCorrupt garbled binary non-pdf stream that cannot be opened"

    response = client.post(
        "/api/runs/upload-pdf",
        data={"answer": "Some answer that requires evidence."},
        files={"file": ("corrupt.pdf", io.BytesIO(corrupt_bytes), "application/pdf")},
    )

    assert response.status_code == 400
    assert "Failed to open PDF document" in response.json()["detail"]


def test_upload_pdf_to_existing_run_and_state_transition(client):
    """Verify attaching a PDF source to an existing run resets stage to awaiting_evidence."""
    # 1. Create run with text source
    res1 = client.post(
        "/api/runs",
        json={
            "answer": "Python was created in 1989.",
            "sources": [{"title": "Source 1", "source_type": "text", "content": "Text content."}],
        },
    )
    run_id = res1.json()["run_id"]

    # 2. Simulate run reaching assessment_completed
    db = TestingSessionLocal()
    run = db.query(Run).filter(Run.id == run_id).first()
    run.current_stage = "assessment_completed"
    run.status = RunStatus.COMPLETED.value
    db.commit()
    db.close()

    # 3. Attach PDF source
    pdf_bytes = create_synthetic_pdf(["Additional PDF reference page content."])
    upload_res = client.post(
        f"/api/runs/{run_id}/sources/pdf",
        data={"title": "Additional Reference Document"},
        files={"file": ("appendix.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )
    assert upload_res.status_code == 201
    source_data = upload_res.json()
    assert source_data["title"] == "Additional Reference Document"
    assert source_data["source_type"] == "pdf"
    assert source_data["page_count"] == 1

    # 4. Verify run stage transitioned back to awaiting_evidence
    status_res = client.get(f"/api/runs/{run_id}/status")
    assert status_res.json()["current_stage"] == "awaiting_evidence"
    assert status_res.json()["status"] == "processing"


def test_upload_pdf_conflict_when_pipeline_active(client):
    """Verify uploading PDF while extraction/retrieval/assessment is active returns 409."""
    res1 = client.post(
        "/api/runs",
        json={
            "answer": "Test answer text.",
            "sources": [{"title": "Text", "source_type": "text", "content": "Sample content."}],
        },
    )
    run_id = res1.json()["run_id"]

    db = TestingSessionLocal()
    run = db.query(Run).filter(Run.id == run_id).first()
    run.current_stage = "assessing_claims"
    db.commit()
    db.close()

    pdf_bytes = create_synthetic_pdf(["PDF page text."])
    upload_res = client.post(
        f"/api/runs/{run_id}/sources/pdf",
        files={"file": ("doc.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )
    assert upload_res.status_code == 409
    assert "Cannot upload sources while run stage 'assessing_claims' is currently processing" in upload_res.json()["detail"]


def test_e2e_pdf_provenance_in_report(client):
    """Verify complete flow: PDF upload -> extraction -> retrieval -> report serialization."""
    pages = [
        "In 1991, Python 0.9.0 was released by Guido van Rossum with classes and exception handling.",
        "In 2000, Python 2.0 was released introducing list comprehensions.",
    ]
    pdf_bytes = create_synthetic_pdf(pages)

    # 1. Upload run with PDF
    res = client.post(
        "/api/runs/upload-pdf",
        data={"answer": "Python 0.9.0 was released in 1991. Python 2.0 introduced list comprehensions."},
        files={"file": ("history.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )
    run_id = res.json()["run_id"]

    # 2. Add claims
    db = TestingSessionLocal()
    c1 = Claim(
        id="c-p1",
        run_id=run_id,
        original_text="Python 0.9.0 was released in 1991.",
        normalized_text="Python 0.9.0 was released in 1991.",
        position_in_answer=0,
    )
    c2 = Claim(
        id="c-p2",
        run_id=run_id,
        original_text="Python 2.0 introduced list comprehensions.",
        normalized_text="Python 2.0 introduced list comprehensions.",
        position_in_answer=1,
    )
    db.add_all([c1, c2])
    run = db.query(Run).filter(Run.id == run_id).first()
    run.current_stage = "awaiting_evidence"
    db.commit()
    db.close()

    # 3. Retrieve evidence
    ret_res = client.post(f"/api/runs/{run_id}/retrieve?top_k=2")
    assert ret_res.status_code == 200

    # 4. Check report
    report_res = client.get(f"/api/runs/{run_id}/report")
    assert report_res.status_code == 200
    report = report_res.json()

    # Check sources
    assert len(report["sources"]) == 1
    pdf_src = report["sources"][0]
    assert pdf_src["source_type"] == "pdf"
    assert pdf_src["page_count"] == 2
    assert pdf_src["scanned_page_count"] == 0

    # Check claims and evidence page provenance
    for claim in report["claims"]:
        assert len(claim["evidence"]) > 0
        for ev in claim["evidence"]:
            assert ev["page_number"] in [1, 2]
            assert ev["source_location"].startswith(f"Page {ev['page_number']}, char ")


def test_backward_compatibility_text_source(client):
    """Verify text sources maintain page_number=None and legacy char offset location format."""
    res = client.post(
        "/api/runs",
        json={
            "answer": "Guido created Python.",
            "sources": [{"title": "Text Doc", "source_type": "text", "content": "Guido van Rossum created Python."}],
        },
    )
    run_id = res.json()["run_id"]

    db = TestingSessionLocal()
    claim = Claim(
        id="c-legacy",
        run_id=run_id,
        original_text="Guido created Python.",
        normalized_text="Guido created Python.",
        position_in_answer=0,
    )
    db.add(claim)
    run = db.query(Run).filter(Run.id == run_id).first()
    run.current_stage = "awaiting_evidence"
    db.commit()
    db.close()

    client.post(f"/api/runs/{run_id}/retrieve?top_k=2")

    report_res = client.get(f"/api/runs/{run_id}/report")
    report = report_res.json()

    src = report["sources"][0]
    assert src["source_type"] == "text"
    assert src["page_count"] is None
    assert src["scanned_page_count"] == 0

    ev = report["claims"][0]["evidence"][0]
    assert ev["page_number"] is None
    assert ev["source_location"].startswith("char ")


def test_metadata_does_not_disclose_full_document_text(client):
    """Verify metadata endpoints do not leak full extracted document text."""
    secret_text = "CONFIDENTIAL_AUDIT_PASSAGE_THAT_MUST_NOT_BE_IN_METADATA_FIELD"
    pages = [f"Page 1 contains {secret_text}.", "Page 2 contains standard reference notes."]
    pdf_bytes = create_synthetic_pdf(pages)

    res = client.post(
        "/api/runs/upload-pdf",
        data={"answer": "Some answer text to verify against PDF."},
        files={"file": ("secret_guide.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )
    assert res.status_code == 201
    run_id = res.json()["run_id"]

    # 1. Check report response
    report_res = client.get(f"/api/runs/{run_id}/report")
    assert report_res.status_code == 200
    report = report_res.json()
    source_meta = json.loads(report["sources"][0]["extraction_metadata"])

    # Metadata must be lightweight and NOT contain pages_content or the secret document text
    assert "pages_content" not in source_meta
    assert "saved_file_path" not in source_meta
    assert secret_text not in json.dumps(source_meta)
    assert source_meta["page_count"] == 2
    assert source_meta["scanned_page_count"] == 0

    # 2. Check source detail endpoint
    source_id = report["sources"][0]["id"]
    source_res = client.get(f"/api/runs/{run_id}/sources/{source_id}")
    assert source_res.status_code == 200
    detail_meta = json.loads(source_res.json()["extraction_metadata"])
    assert "pages_content" not in detail_meta
    assert secret_text not in json.dumps(detail_meta)


def test_upload_additional_pdf_invalidates_stale_verdicts_and_evidence(client):
    """Verify attaching an additional PDF clears stale evidence and resets previous claim assessments."""
    pdf1_bytes = create_synthetic_pdf(["Original reference text that supports claim."])

    # 1. Create run with initial PDF
    res1 = client.post(
        "/api/runs/upload-pdf",
        data={"answer": "First statement is true."},
        files={"file": ("doc1.pdf", io.BytesIO(pdf1_bytes), "application/pdf")},
    )
    run_id = res1.json()["run_id"]

    # 2. Simulate completed assessment with verdict and evidence
    db = TestingSessionLocal()
    run = db.query(Run).filter(Run.id == run_id).first()
    source = run.sources[0]
    chunk = SourceChunk(
        source_id=source.id,
        content="Original reference text that supports claim.",
        start_offset=0,
        end_offset=44,
        page_number=1,
    )
    db.add(chunk)
    db.flush()

    claim = Claim(
        id="c-stale-test",
        run_id=run_id,
        original_text="First statement is true.",
        normalized_text="First statement is true.",
        position_in_answer=0,
        verdict=Verdict.SUPPORTED.value,
        assessment_status=AssessmentStatus.ASSESSED.value,
        reasoning="Prior evidence conclusively proved this statement.",
        limitations="None noted.",
    )
    db.add(claim)
    db.flush()

    ev = Evidence(
        claim_id=claim.id,
        source_id=source.id,
        chunk_id=chunk.id,
        excerpt=chunk.content,
        source_location="Page 1, char 0-44",
        relationship="supports",
        relevance_score=1.5,
        explanation="Supports statement directly.",
    )
    db.add(ev)
    run.current_stage = "assessment_completed"
    run.status = RunStatus.COMPLETED.value
    db.commit()

    # Verify report initially shows assessed verdict and evidence
    initial_report = client.get(f"/api/runs/{run_id}/report").json()
    assert initial_report["summary"]["supported"] == 1
    assert initial_report["claims"][0]["verdict"] == "supported"
    assert len(initial_report["claims"][0]["evidence"]) == 1

    # 3. Upload additional PDF reference
    pdf2_bytes = create_synthetic_pdf(["Secondary reference document."])
    upload_res = client.post(
        f"/api/runs/{run_id}/sources/pdf",
        data={"title": "Doc 2"},
        files={"file": ("doc2.pdf", io.BytesIO(pdf2_bytes), "application/pdf")},
    )
    assert upload_res.status_code == 201

    # 4. Verify stale state invalidation in DB and report
    updated_run = db.query(Run).filter(Run.id == run_id).first()
    assert updated_run.current_stage == "awaiting_evidence"
    assert updated_run.status == RunStatus.PROCESSING.value

    # Claims must be reset to pending with no verdict or reasoning
    updated_claim = db.query(Claim).filter(Claim.id == "c-stale-test").first()
    assert updated_claim.verdict is None
    assert updated_claim.assessment_status == AssessmentStatus.PENDING.value
    assert updated_claim.reasoning is None
    assert updated_claim.limitations is None

    # Old evidence must be completely cleared
    evidence_count = db.query(Evidence).filter(Evidence.claim_id == "c-stale-test").count()
    assert evidence_count == 0

    # User report must reflect clean pending state
    updated_report = client.get(f"/api/runs/{run_id}/report").json()
    assert updated_report["summary"]["supported"] == 0
    assert updated_report["claims"][0]["verdict"] is None
    assert len(updated_report["claims"][0]["evidence"]) == 0
    db.close()


def test_concurrent_pdf_uploads_return_409(client):
    """Verify concurrent uploads to the same run are rejected with HTTP 409 Conflict."""
    res1 = client.post(
        "/api/runs",
        json={"answer": "Valid answer text.", "sources": [{"title": "Text", "source_type": "text", "content": "Text."}]},
    )
    run_id = res1.json()["run_id"]

    from routes.runs import _active_pdf_uploads
    _active_pdf_uploads.add(run_id)

    try:
        pdf_bytes = create_synthetic_pdf(["Page text."])
        upload_res = client.post(
            f"/api/runs/{run_id}/sources/pdf",
            files={"file": ("concurrent.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )
        assert upload_res.status_code == 409
        assert "already in progress" in upload_res.json()["detail"]
    finally:
        _active_pdf_uploads.discard(run_id)


def test_failed_upload_rollback_cleans_orphaned_pdf_file(client):
    """Verify that if an upload transaction fails, the saved PDF file is cleaned up from disk."""
    res1 = client.post(
        "/api/runs",
        json={"answer": "Valid answer text.", "sources": [{"title": "Text", "source_type": "text", "content": "Text."}]},
    )
    run_id = res1.json()["run_id"]

    pdf_bytes = create_synthetic_pdf(["Page content to test rollback."])

    with patch("sqlalchemy.orm.Session.commit", side_effect=RuntimeError("Simulated DB connection failure")):
        upload_res = client.post(
            f"/api/runs/{run_id}/sources/pdf",
            files={"file": ("rollback.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )
        assert upload_res.status_code == 500

    # Verify no orphaned files with this timestamp exist
    storage_dir = get_pdf_storage_dir()
    # Confirm directory exists and no corrupt leftovers
    assert storage_dir.exists()


def test_legacy_sqlite_schema_migration():
    """Verify init_db cleanly and idempotently migrates a legacy SQLite schema without Phase 6 columns."""
    from database import init_db

    legacy_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # 1. Create legacy schema mimicking Phase 1-5
    with legacy_engine.connect() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE runs (
                id VARCHAR(36) PRIMARY KEY,
                original_answer TEXT NOT NULL,
                status VARCHAR(32) NOT NULL,
                current_stage VARCHAR(64) NOT NULL,
                created_at DATETIME NOT NULL,
                completed_at DATETIME,
                error_message TEXT
            );
        """)
        conn.exec_driver_sql("""
            CREATE TABLE sources (
                id VARCHAR(36) PRIMARY KEY,
                run_id VARCHAR(36) NOT NULL,
                title VARCHAR(255) NOT NULL,
                source_type VARCHAR(32) NOT NULL,
                processing_status VARCHAR(32) NOT NULL,
                failure_reason TEXT,
                raw_content TEXT,
                content_length INTEGER NOT NULL,
                content_hash VARCHAR(64),
                created_at DATETIME NOT NULL
            );
        """)
        conn.exec_driver_sql("""
            CREATE TABLE source_chunks (
                id VARCHAR(36) PRIMARY KEY,
                source_id VARCHAR(36) NOT NULL,
                content TEXT NOT NULL,
                start_offset INTEGER NOT NULL,
                end_offset INTEGER NOT NULL,
                created_at DATETIME NOT NULL
            );
        """)
        conn.exec_driver_sql("""
            CREATE TABLE claims (
                id VARCHAR(36) PRIMARY KEY,
                run_id VARCHAR(36) NOT NULL,
                original_text TEXT NOT NULL,
                normalized_text TEXT NOT NULL,
                position_in_answer INTEGER,
                verdict VARCHAR(32),
                assessment_status VARCHAR(32) NOT NULL,
                reasoning TEXT,
                limitations TEXT,
                created_at DATETIME NOT NULL
            );
        """)
        conn.exec_driver_sql("""
            CREATE TABLE evidence (
                id VARCHAR(36) PRIMARY KEY,
                claim_id VARCHAR(36) NOT NULL,
                source_id VARCHAR(36) NOT NULL,
                chunk_id VARCHAR(36),
                excerpt TEXT NOT NULL,
                source_location VARCHAR(128) NOT NULL,
                relationship VARCHAR(32) NOT NULL,
                relevance_score FLOAT,
                explanation TEXT,
                created_at DATETIME NOT NULL
            );
        """)
        # Insert legacy source row
        conn.exec_driver_sql("""
            INSERT INTO sources (id, run_id, title, source_type, processing_status, content_length, created_at)
            VALUES ('s-legacy', 'r-1', 'Legacy Text', 'text', 'success', 20, '2026-01-01 00:00:00');
        """)
        conn.commit()

    # 2. Run init_db on legacy engine
    init_db(legacy_engine)

    # 3. Verify columns were added safely
    with legacy_engine.connect() as conn:
        res_src = conn.exec_driver_sql("PRAGMA table_info(sources)")
        src_cols = [row[1] for row in res_src.fetchall()]
        assert "page_count" in src_cols
        assert "scanned_page_count" in src_cols
        assert "extraction_metadata" in src_cols

        res_chunk = conn.exec_driver_sql("PRAGMA table_info(source_chunks)")
        chunk_cols = [row[1] for row in res_chunk.fetchall()]
        assert "page_number" in chunk_cols

        res_ev = conn.exec_driver_sql("PRAGMA table_info(evidence)")
        ev_cols = [row[1] for row in res_ev.fetchall()]
        assert "page_number" in ev_cols

        # Check existing row preserved
        row = conn.exec_driver_sql("SELECT id, title, page_count FROM sources WHERE id = 's-legacy'").fetchone()
        assert row[0] == "s-legacy"
        assert row[1] == "Legacy Text"
        assert row[2] is None


def test_pdf_unicode_tables_and_special_characters():
    """Verify PDF with Unicode, accents, currency, and table formatting chunks with exact offsets."""
    unicode_page = (
        "Item\tValue\tStatus\n"
        "Revenue\t$1,250,000.50\tConfirmed\n"
        "Growth\t+18.4%\tExact\n"
        "Café\tnaïve façade\tValidated"
    )
    pdf_bytes = create_synthetic_pdf([unicode_page])

    source_id = "test-unicode-source"
    result = extract_and_validate_pdf(
        file_bytes=pdf_bytes,
        original_filename="unicode_table.pdf",
        source_id=source_id,
        save_to_disk=True,
    )

    page_records = get_pdf_page_texts(source_id, result.raw_content)
    assert len(page_records) == 1
    page_num, page_text = page_records[0]
    assert page_num == 1
    assert "Revenue\t$1,250,000.50\tConfirmed" in page_text
    assert "Café\tnaïve façade\tValidated" in page_text

    from services.chunker import chunk_source_text
    chunks = chunk_source_text(page_text)
    assert len(chunks) > 0
    for ch in chunks:
        # Invariant: exact substring match with Python character offsets
        assert page_text[ch.start_offset:ch.end_offset] == ch.content

    cleanup_pdf_file(source_id)

