"""Tests for database ORM models and relationships using an in-memory SQLite database."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models.db_models import Run, Source, SourceChunk, Claim, Evidence, QuoteAudit


@pytest.fixture
def db_session():
    """Create an isolated in-memory SQLite database for test execution."""
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=test_engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=test_engine)


def test_db_models_crud_and_relationships(db_session):
    """Test creation and linkage of Run, Source, Chunks, Claims, Evidence, and QuoteAudits."""
    # 1. Create a Run
    run = Run(
        original_answer="Python was released in 1991 by Guido van Rossum.",
        status="processing",
        current_stage="retrieving",
    )
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)

    assert run.id is not None
    assert run.created_at is not None

    # 2. Add a Source and SourceChunk
    source = Source(
        run_id=run.id,
        title="Python History Document",
        source_type="text",
        processing_status="success",
        raw_content="Python was conceived in late 1980s and first released in 1991 by Guido van Rossum.",
        content_length=83,
        content_hash="abc123hash",
    )
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)

    chunk = SourceChunk(
        source_id=source.id,
        content=source.raw_content,
        start_offset=0,
        end_offset=83,
        page_number=None,
    )
    db_session.add(chunk)
    db_session.commit()

    # 3. Add a Claim
    claim = Claim(
        run_id=run.id,
        original_text="Python was released in 1991",
        normalized_text="Python was released in 1991",
        position_in_answer=0,
        verdict="supported",
        assessment_status="assessed",
        reasoning="Document explicitly states first released in 1991.",
    )
    db_session.add(claim)
    db_session.commit()
    db_session.refresh(claim)

    # 4. Add Evidence linking Claim and Source
    evidence = Evidence(
        claim_id=claim.id,
        source_id=source.id,
        chunk_id=chunk.id,
        excerpt="first released in 1991",
        source_location="chars 45-68",
        relationship="supports",
        relevance_score=0.98,
    )
    db_session.add(evidence)

    # 5. Add QuoteAudit
    quote_audit = QuoteAudit(
        run_id=run.id,
        quotation_text="released in 1991",
        match_status="exact",
        matched_source_id=source.id,
        source_location="chars 45-61",
    )
    db_session.add(quote_audit)
    db_session.commit()

    # Verify relationships from the Run object
    db_session.refresh(run)
    assert len(run.sources) == 1
    assert run.sources[0].title == "Python History Document"
    assert len(run.sources[0].chunks) == 1

    assert len(run.claims) == 1
    assert run.claims[0].original_text == "Python was released in 1991"
    assert len(run.claims[0].evidence_items) == 1
    assert run.claims[0].evidence_items[0].source_id == source.id

    assert len(run.quote_audits) == 1


def test_cascade_delete(db_session):
    """Verify that deleting a Run cascades to child sources and claims."""
    run = Run(original_answer="Sample answer", status="completed", current_stage="done")
    db_session.add(run)
    db_session.commit()

    source = Source(run_id=run.id, title="Doc", source_type="text")
    claim = Claim(run_id=run.id, original_text="Statement", normalized_text="Statement")
    db_session.add_all([source, claim])
    db_session.commit()

    run_id = run.id
    # Delete the run
    db_session.delete(run)
    db_session.commit()

    # Verify children were deleted
    remaining_sources = db_session.query(Source).filter_by(run_id=run_id).all()
    remaining_claims = db_session.query(Claim).filter_by(run_id=run_id).all()
    assert len(remaining_sources) == 0
    assert len(remaining_claims) == 0
