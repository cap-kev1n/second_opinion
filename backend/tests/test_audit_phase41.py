"""Adversarial and reliability audit tests for Phase 4.1.

Verifies:
1. Logical consistency invariants and verdict correctness.
2. Cross-source conflicts, source attribution, and immutability.
3. Concurrency, lifecycle integrity, and stuck-state recovery.
4. Evidence changes, stale assessment invalidation, and versioning.
5. Large-run stress testing (50 and 100 claims).
6. Backward-compatibility migrations for existing databases.
"""

import asyncio
import os
import sqlite3
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base, init_db
from models.db_models import Run, Source, Claim, Evidence
from models.schemas import (
    RunStatus,
    AssessmentStatus,
    Verdict,
    EvidenceRelationship,
    utc_now,
)
from services.claim_assessor import (
    validate_model_assessment,
    assess_and_persist_claims,
    _active_assessments,
)
from services.evidence_orchestrator import retrieve_and_persist_evidence
from services.llm_client import BaseLLMClient


class DeterministicMockClient(BaseLLMClient):
    """Deterministic mock client returning scripted responses based on claim or call."""

    def __init__(self, scripted_responses=None, default_response=None, delay=0.0):
        self._scripted = scripted_responses or {}
        self._default = default_response or {
            "verdict": "supported",
            "reasoning": "Default deterministic mock support.",
            "evidence_assessments": [],
            "limitations": [],
        }
        self.call_count = 0
        self.delay = delay
        self.calls_by_claim = {}

    def is_configured(self) -> bool:
        return True

    async def extract_claims(self, answer_text: str):
        return []

    async def assess_claim(
        self,
        claim_id: str,
        original_text: str,
        normalized_text: str,
        position_in_answer: int | None,
        evidence_items: list[dict],
    ):
        self.call_count += 1
        self.calls_by_claim[claim_id] = self.calls_by_claim.get(claim_id, 0) + 1
        if self.delay > 0:
            await asyncio.sleep(self.delay)

        if claim_id in self._scripted:
            resp = self._scripted[claim_id]
            if isinstance(resp, Exception):
                raise resp
            return resp

        # Inject evidence_items into default response if needed
        resp = dict(self._default)
        if not resp.get("evidence_assessments") and evidence_items:
            resp["evidence_assessments"] = [
                {
                    "evidence_id": ev["id"],
                    "relationship": "supports",
                    "explanation": f"Supports claim '{normalized_text}'.",
                }
                for ev in evidence_items
            ]
        return resp


def get_fresh_test_db(db_name="test_audit.db"):
    db_path = f"sqlite:///./{db_name}"
    eng = create_engine(db_path, connect_args={"check_same_thread": False})
    Base.metadata.drop_all(bind=eng)
    Base.metadata.create_all(bind=eng)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=eng)
    return Session(), eng, db_name


def cleanup_test_db(db, eng, db_name):
    db.close()
    eng.dispose()
    if os.path.exists(db_name):
        try:
            os.remove(db_name)
        except Exception:
            pass


def seed_audit_run(db, claim_count=1, evidence_per_claim=2):
    run = Run(
        original_answer="The speed of light in vacuum is approximately 300,000 km/s.",
        status=RunStatus.PROCESSING.value,
        current_stage="awaiting_assessment",
        created_at=utc_now(),
    )
    db.add(run)
    db.flush()

    source = Source(
        run_id=run.id,
        title="Physics Principles",
        source_type="text",
        raw_content="The speed of light in vacuum is exactly 299,792,458 m/s, approximately 300,000 km/s.",
        content_length=95,
        created_at=utc_now(),
    )
    db.add(source)
    db.flush()

    claim_ids = []
    evidence_ids = []
    for c_idx in range(claim_count):
        claim = Claim(
            run_id=run.id,
            original_text=f"Claim text #{c_idx + 1}",
            normalized_text=f"Normalized statement #{c_idx + 1}",
            position_in_answer=c_idx * 10,
            verdict=None,
            assessment_status=AssessmentStatus.PENDING.value,
            created_at=utc_now(),
        )
        db.add(claim)
        db.flush()
        claim_ids.append(claim.id)

        for e_idx in range(evidence_per_claim):
            ev = Evidence(
                claim_id=claim.id,
                source_id=source.id,
                excerpt=f"Physics source passage for claim {c_idx + 1} evidence {e_idx + 1}.",
                source_location=f"char {e_idx * 20}-{e_idx * 20 + 20}",
                relationship=EvidenceRelationship.CANDIDATE.value,
                relevance_score=3.5 - (0.5 * e_idx),
                created_at=utc_now(),
            )
            db.add(ev)
            db.flush()
            evidence_ids.append(ev.id)

    db.commit()
    return run.id, claim_ids, evidence_ids


# ---------------------------------------------------------------------------
# 1. VERDICT CORRECTNESS AND INVARIANT TESTS
# ---------------------------------------------------------------------------

def test_validation_rejects_supported_when_only_partially_supported():
    """Invariant: Verdict cannot be 'supported' if evidence only partially supports the claim."""
    valid_ids = {"ev-1"}
    raw = {
        "verdict": "supported",
        "reasoning": "The passage partially mentions the claim.",
        "evidence_assessments": [
            {
                "evidence_id": "ev-1",
                "relationship": "partially_supports",
                "explanation": "Supports only the speed aspect, not the vacuum medium.",
            }
        ],
        "limitations": ["Vacuum medium unverified."],
    }
    with pytest.raises(ValueError, match="requires at least one directly supporting"):
        validate_model_assessment(raw, valid_ids)


def test_validation_rejects_supported_when_conflicting_evidence_exists():
    """Invariant: Verdict cannot be 'supported' if candidate evidence contains contradictory passages."""
    valid_ids = {"ev-1", "ev-2"}
    raw = {
        "verdict": "supported",
        "reasoning": "Source 1 supports it even though Source 2 contradicts it.",
        "evidence_assessments": [
            {
                "evidence_id": "ev-1",
                "relationship": "supports",
                "explanation": "Directly supports claim.",
            },
            {
                "evidence_id": "ev-2",
                "relationship": "contradicts",
                "explanation": "Contradicts claim directly.",
            },
        ],
        "limitations": [],
    }
    with pytest.raises(ValueError, match="Conflicting evidence must be resolved as 'ambiguous'"):
        validate_model_assessment(raw, valid_ids)


def test_validation_rejects_contradicted_when_supporting_evidence_exists():
    """Invariant: Verdict cannot be 'contradicted' if candidate evidence contains supporting passages."""
    valid_ids = {"ev-1", "ev-2"}
    raw = {
        "verdict": "contradicted",
        "reasoning": "Contradicts even though another source supports.",
        "evidence_assessments": [
            {
                "evidence_id": "ev-1",
                "relationship": "supports",
                "explanation": "Supports.",
            },
            {
                "evidence_id": "ev-2",
                "relationship": "contradicts",
                "explanation": "Contradicts.",
            },
        ],
        "limitations": [],
    }
    with pytest.raises(ValueError, match="Conflicting evidence must be resolved as 'ambiguous'"):
        validate_model_assessment(raw, valid_ids)


def test_validation_rejects_ambiguous_when_all_evidence_is_irrelevant():
    """Invariant: Ambiguous cannot be assigned when all evidence is irrelevant."""
    valid_ids = {"ev-1"}
    raw = {
        "verdict": "ambiguous",
        "reasoning": "Unclear relevance.",
        "evidence_assessments": [
            {
                "evidence_id": "ev-1",
                "relationship": "irrelevant",
                "explanation": "Mentions unrelated topic.",
            }
        ],
        "limitations": [],
    }
    with pytest.raises(ValueError, match="When all evaluated evidence items are 'irrelevant'"):
        validate_model_assessment(raw, valid_ids)


def test_validation_enforces_insufficiently_supported_when_all_irrelevant():
    """Invariant: When all evidence is irrelevant, verdict must be insufficiently_supported."""
    valid_ids = {"ev-1"}
    raw = {
        "verdict": "supported",
        "reasoning": "Claim is presumed true.",
        "evidence_assessments": [
            {
                "evidence_id": "ev-1",
                "relationship": "irrelevant",
                "explanation": "Unrelated passage.",
            }
        ],
        "limitations": [],
    }
    with pytest.raises(ValueError, match="verdict must be 'insufficiently_supported'"):
        validate_model_assessment(raw, valid_ids)


def test_conflicting_sources_must_be_ambiguous():
    """When one passage supports and another contradicts, verdict must be ambiguous."""
    valid_ids = {"ev-1", "ev-2"}
    raw = {
        "verdict": "ambiguous",
        "reasoning": "Source A states 300,000 km/s while Source B states 200,000 km/s.",
        "evidence_assessments": [
            {
                "evidence_id": "ev-1",
                "relationship": "supports",
                "explanation": "States speed of light is 300,000 km/s.",
            },
            {
                "evidence_id": "ev-2",
                "relationship": "contradicts",
                "explanation": "States speed of light is 200,000 km/s.",
            },
        ],
        "limitations": ["Sources present conflicting measurements."],
    }
    validated = validate_model_assessment(raw, valid_ids)
    assert validated["verdict"] == "ambiguous"
    assert len(validated["evidence_assessments"]) == 2


# ---------------------------------------------------------------------------
# 2. SOURCE ATTRIBUTION AND IMMUTABILITY TESTS
# ---------------------------------------------------------------------------

def test_source_and_claim_immutability_after_repeated_assessments():
    """Verifies that source content, original answer, claim text, and retrieval scores are immutable."""
    async def _run():
        db, eng, db_name = get_fresh_test_db("test_immutability.db")
        try:
            run_id, claim_ids, evidence_ids = seed_audit_run(db, claim_count=1, evidence_per_claim=2)

            run = db.query(Run).filter(Run.id == run_id).first()
            source = run.sources[0]
            claim = run.claims[0]
            ev1 = claim.evidence_items[0]

            orig_answer = str(run.original_answer)
            orig_source_content = str(source.raw_content)
            orig_claim_text = str(claim.original_text)
            orig_score = float(ev1.relevance_score)

            # Perform initial assessment
            mock_client = DeterministicMockClient(default_response={
                "verdict": "supported",
                "reasoning": "Confirmed by physics text.",
                "evidence_assessments": [
                    {"evidence_id": evidence_ids[0], "relationship": "supports", "explanation": "Direct statement."},
                    {"evidence_id": evidence_ids[1], "relationship": "partially_supports", "explanation": "Partial context."},
                ],
                "limitations": [],
            })

            await assess_and_persist_claims(run_id=run_id, db=db, client=mock_client)

            # Verify immutability
            db.refresh(run)
            db.refresh(source)
            db.refresh(claim)
            db.refresh(ev1)

            assert run.original_answer == orig_answer
            assert source.raw_content == orig_source_content
            assert claim.original_text == orig_claim_text
            assert ev1.relevance_score == orig_score

            # Perform forced reassessment
            mock_client_2 = DeterministicMockClient(default_response={
                "verdict": "ambiguous",
                "reasoning": "Re-evaluated with updated nuance.",
                "evidence_assessments": [
                    {"evidence_id": evidence_ids[0], "relationship": "supports", "explanation": "Passage 1 supports."},
                    {"evidence_id": evidence_ids[1], "relationship": "contradicts", "explanation": "Passage 2 contradicts."},
                ],
                "limitations": ["Discrepancy noted."],
            })
            await assess_and_persist_claims(run_id=run_id, db=db, client=mock_client_2, force_reassess=True)

            db.refresh(run)
            db.refresh(source)
            db.refresh(claim)
            db.refresh(ev1)

            assert run.original_answer == orig_answer
            assert source.raw_content == orig_source_content
            assert claim.original_text == orig_claim_text
            assert ev1.relevance_score == orig_score
            assert claim.verdict == "ambiguous"

        finally:
            cleanup_test_db(db, eng, db_name)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# 3. CONCURRENCY, LIFECYCLE, AND STUCK-STATE RECOVERY TESTS
# ---------------------------------------------------------------------------

def test_forced_reassessment_while_active_in_process_returns_409():
    """Forced reassessment while another assessment is active in-process is rejected with 409 Conflict."""
    async def _run():
        db, eng, db_name = get_fresh_test_db("test_active_conflict.db")
        try:
            run_id, _, _ = seed_audit_run(db, claim_count=1)

            # Simulate an active assessment in process
            _active_assessments.add(run_id)

            mock_client = DeterministicMockClient()
            with pytest.raises(HTTPException) as exc_info:
                await assess_and_persist_claims(run_id=run_id, db=db, client=mock_client, force_reassess=True)

            assert exc_info.value.status_code == 409
            assert "actively in progress" in exc_info.value.detail

        finally:
            _active_assessments.discard(run_id)
            cleanup_test_db(db, eng, db_name)

    asyncio.run(_run())


def test_recovering_stuck_assessing_claims_state():
    """When a worker crashed and left a run in assessing_claims, force_reassess recovers it safely."""
    async def _run():
        db, eng, db_name = get_fresh_test_db("test_stuck_recovery.db")
        try:
            run_id, _, evidence_ids = seed_audit_run(db, claim_count=1)

            # Simulate crash: stage is assessing_claims, but NOT in active memory
            run = db.query(Run).filter(Run.id == run_id).first()
            run.current_stage = "assessing_claims"
            db.commit()

            assert run_id not in _active_assessments

            # Standard assess call without force_reassess still returns 409 to be safe
            mock_client = DeterministicMockClient()
            with pytest.raises(HTTPException) as exc_info:
                await assess_and_persist_claims(run_id=run_id, db=db, client=mock_client, force_reassess=False)
            assert exc_info.value.status_code == 409

            # With force_reassess=True, recovery policy kicks in and re-evaluates
            mock_client_recovery = DeterministicMockClient(default_response={
                "verdict": "supported",
                "reasoning": "Recovered assessment completed.",
                "evidence_assessments": [
                    {"evidence_id": evidence_ids[0], "relationship": "supports", "explanation": "Verified."},
                    {"evidence_id": evidence_ids[1], "relationship": "supports", "explanation": "Verified."},
                ],
                "limitations": [],
            })
            recovered_run = await assess_and_persist_claims(
                run_id=run_id, db=db, client=mock_client_recovery, force_reassess=True
            )

            assert recovered_run.current_stage == "assessment_completed"
            assert recovered_run.claims[0].verdict == "supported"

        finally:
            cleanup_test_db(db, eng, db_name)

    asyncio.run(_run())


def test_assessment_rejected_during_extraction_or_retrieval():
    """Assessment is rejected with 409 if extraction or retrieval is actively in progress."""
    async def _run():
        db, eng, db_name = get_fresh_test_db("test_stage_conflict.db")
        try:
            run_id, _, _ = seed_audit_run(db, claim_count=1)
            run = db.query(Run).filter(Run.id == run_id).first()

            # Test during extracting_claims
            run.current_stage = "extracting_claims"
            db.commit()

            mock_client = DeterministicMockClient()
            with pytest.raises(HTTPException) as exc_info:
                await assess_and_persist_claims(run_id=run_id, db=db, client=mock_client)
            assert exc_info.value.status_code == 409
            assert "Extracting claims is currently in progress" in exc_info.value.detail

            # Test during retrieving_evidence
            run.current_stage = "retrieving_evidence"
            db.commit()

            with pytest.raises(HTTPException) as exc_info2:
                await assess_and_persist_claims(run_id=run_id, db=db, client=mock_client)
            assert exc_info2.value.status_code == 409
            assert "Retrieving evidence is currently in progress" in exc_info2.value.detail

        finally:
            cleanup_test_db(db, eng, db_name)

    asyncio.run(_run())


def test_simultaneous_assessments_different_runs_succeed():
    """Simultaneous assessment requests for different runs run independently without collision."""
    async def _run():
        db, eng, db_name = get_fresh_test_db("test_multi_run_concurrency.db")
        try:
            run_id_1, _, ev_ids_1 = seed_audit_run(db, claim_count=1)
            run_id_2, _, ev_ids_2 = seed_audit_run(db, claim_count=1)

            mock_client = DeterministicMockClient(delay=0.05)

            # Run both concurrently
            res1, res2 = await asyncio.gather(
                assess_and_persist_claims(run_id=run_id_1, db=db, client=mock_client),
                assess_and_persist_claims(run_id=run_id_2, db=db, client=mock_client),
            )

            assert res1.current_stage == "assessment_completed"
            assert res2.current_stage == "assessment_completed"
            assert res1.claims[0].verdict == "supported"
            assert res2.claims[0].verdict == "supported"

        finally:
            cleanup_test_db(db, eng, db_name)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# 4. EVIDENCE CHANGES AND STALE ASSESSMENT INVALIDATION
# ---------------------------------------------------------------------------

def test_evidence_re_retrieval_invalidates_stale_assessments():
    """Re-retrieving evidence completely invalidates prior verdicts, reasoning, and limitations."""
    db, eng, db_name = get_fresh_test_db("test_re_retrieval_invalidation.db")
    try:
        run_id, claim_ids, evidence_ids = seed_audit_run(db, claim_count=1, evidence_per_claim=2)

        # First, set an existing completed assessment
        run = db.query(Run).filter(Run.id == run_id).first()
        claim = run.claims[0]
        claim.verdict = Verdict.SUPPORTED.value
        claim.assessment_status = AssessmentStatus.ASSESSED.value
        claim.reasoning = "Old valid assessment based on earlier chunks."
        claim.limitations = "Old limitations."
        run.current_stage = "assessment_completed"
        run.completed_at = utc_now()
        db.commit()

        # Re-run evidence retrieval
        updated_run = retrieve_and_persist_evidence(run_id=run_id, db=db, top_k=2)

        # Invariant check: all prior assessment fields must be completely wiped out
        assert updated_run.current_stage == "awaiting_assessment"
        assert updated_run.completed_at is None
        assert updated_run.claims[0].verdict is None
        assert updated_run.claims[0].assessment_status == AssessmentStatus.PENDING.value
        assert updated_run.claims[0].reasoning is None
        assert updated_run.claims[0].limitations is None

        # Evidence records are candidate with no stale explanations
        for ev in updated_run.claims[0].evidence_items:
            assert ev.relationship == EvidenceRelationship.CANDIDATE.value
            assert ev.explanation is None

    finally:
        cleanup_test_db(db, eng, db_name)


def test_failed_reassessment_cleans_up_stale_evidence_relationships():
    """If a forced reassessment fails operationally, prior evidence relationships are reset to CANDIDATE."""
    async def _run():
        db, eng, db_name = get_fresh_test_db("test_failed_reassessment.db")
        try:
            run_id, claim_ids, evidence_ids = seed_audit_run(db, claim_count=1, evidence_per_claim=1)

            # Initial successful assessment
            mock_client_1 = DeterministicMockClient(default_response={
                "verdict": "supported",
                "reasoning": "First run success.",
                "evidence_assessments": [
                    {"evidence_id": evidence_ids[0], "relationship": "supports", "explanation": "Supported."}
                ],
                "limitations": [],
            })
            await assess_and_persist_claims(run_id=run_id, db=db, client=mock_client_1)

            ev = db.query(Evidence).filter(Evidence.id == evidence_ids[0]).first()
            assert ev.relationship == "supports"
            assert ev.explanation == "Supported."

            # Second assessment fails operationally
            mock_client_fail = DeterministicMockClient(scripted_responses={
                claim_ids[0]: RuntimeError("Gemini 503 Provider Unavailable")
            })

            run_failed = await assess_and_persist_claims(
                run_id=run_id, db=db, client=mock_client_fail, force_reassess=True
            )

            # Invariant: verdict is None, status is failed, AND evidence is reset to CANDIDATE
            claim = run_failed.claims[0]
            assert claim.verdict is None
            assert claim.assessment_status == AssessmentStatus.FAILED.value
            assert "Operational assessment error" in claim.reasoning

            ev_after = db.query(Evidence).filter(Evidence.id == evidence_ids[0]).first()
            assert ev_after.relationship == EvidenceRelationship.CANDIDATE.value
            assert ev_after.explanation is None

        finally:
            cleanup_test_db(db, eng, db_name)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# 5. LARGE-RUN BEHAVIOR (50 AND 100 CLAIMS)
# ---------------------------------------------------------------------------

def test_large_run_50_claims_bounded_concurrency_and_performance():
    """Verify assessment of 50 claims completes cleanly with bounded concurrency."""
    async def _run():
        db, eng, db_name = get_fresh_test_db("test_50_claims.db")
        try:
            run_id, claim_ids, evidence_ids = seed_audit_run(db, claim_count=50, evidence_per_claim=1)

            mock_client = DeterministicMockClient(delay=0.001)

            result_run = await assess_and_persist_claims(
                run_id=run_id, db=db, client=mock_client, concurrency_limit=5
            )

            assert result_run.current_stage == "assessment_completed"
            assert len(result_run.claims) == 50
            assert all(c.verdict == "supported" for c in result_run.claims)
            assert mock_client.call_count == 50

            # Verify retry without force_reassess skips all 50 claims
            mock_client_retry = DeterministicMockClient()
            retry_run = await assess_and_persist_claims(
                run_id=run_id, db=db, client=mock_client_retry, force_reassess=False
            )
            assert retry_run.current_stage == "assessment_completed"
            assert mock_client_retry.call_count == 0  # Zero additional LLM calls!

        finally:
            cleanup_test_db(db, eng, db_name)

    asyncio.run(_run())


def test_large_run_100_claims_partial_failure_and_resumability():
    """Verify run with 100 claims handles partial operational failures and cleanly resumes."""
    async def _run():
        db, eng, db_name = get_fresh_test_db("test_100_claims.db")
        try:
            run_id, claim_ids, evidence_ids = seed_audit_run(db, claim_count=100, evidence_per_claim=1)

            # Script 5 claims to fail operationally
            failed_claim_ids = set(claim_ids[10:15])
            scripted = {cid: RuntimeError("Timeout calling provider") for cid in failed_claim_ids}

            mock_client = DeterministicMockClient(scripted_responses=scripted, delay=0.0005)

            result_run = await assess_and_persist_claims(
                run_id=run_id, db=db, client=mock_client, concurrency_limit=5
            )

            assert result_run.current_stage == "assessment_partial"
            assessed_count = sum(1 for c in result_run.claims if c.assessment_status == AssessmentStatus.ASSESSED.value)
            failed_count = sum(1 for c in result_run.claims if c.assessment_status == AssessmentStatus.FAILED.value)

            assert assessed_count == 95
            assert failed_count == 5

            # Retry without force_reassess: should ONLY execute the 5 failed claims!
            mock_client_retry = DeterministicMockClient(delay=0.0005)
            retry_run = await assess_and_persist_claims(
                run_id=run_id, db=db, client=mock_client_retry, force_reassess=False
            )

            assert retry_run.current_stage == "assessment_completed"
            assert mock_client_retry.call_count == 5  # Exactly 5 calls!
            assert all(c.assessment_status == AssessmentStatus.ASSESSED.value for c in retry_run.claims)

        finally:
            cleanup_test_db(db, eng, db_name)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# 6. DATABASE COMPATIBILITY AND MIGRATION
# ---------------------------------------------------------------------------

def test_database_backward_compatibility_migration_for_missing_explanation_column():
    """Verify that an older SQLite database lacking Evidence.explanation is automatically migrated."""
    db_name = "test_legacy_db.db"
    if os.path.exists(db_name):
        os.remove(db_name)

    # Manually create older schema without explanation column
    conn = sqlite3.connect(db_name)
    cur = conn.cursor()
    cur.execute("""
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
    cur.execute("""
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
    cur.execute("""
    CREATE TABLE claims (
        id VARCHAR(36) PRIMARY KEY,
        run_id VARCHAR(36) NOT NULL,
        original_text TEXT NOT NULL,
        normalized_text TEXT NOT NULL,
        position_in_answer INTEGER,
        verdict VARCHAR(32),
        assessment_status VARCHAR(32) NOT NULL,
        created_at DATETIME NOT NULL
    );
    """)
    cur.execute("""
    CREATE TABLE evidence (
        id VARCHAR(36) PRIMARY KEY,
        claim_id VARCHAR(36) NOT NULL,
        source_id VARCHAR(36) NOT NULL,
        chunk_id VARCHAR(36),
        excerpt TEXT NOT NULL,
        source_location VARCHAR(255) NOT NULL,
        relationship VARCHAR(32) NOT NULL,
        relevance_score FLOAT,
        created_at DATETIME NOT NULL
    );
    """)
    # Insert legacy row without explanation
    cur.execute("""
    INSERT INTO evidence VALUES (
        'ev-legacy-1', 'claim-1', 'source-1', NULL, 'Sample excerpt', 'char 0-10', 'candidate', 2.5, '2026-10-10 12:00:00'
    );
    """)
    conn.commit()
    conn.close()

    # Now bind SQLAlchemy engine and call init_db
    eng = create_engine(f"sqlite:///./{db_name}", connect_args={"check_same_thread": False})
    init_db(target_engine=eng)

    Session = sessionmaker(autocommit=False, autoflush=False, bind=eng)
    session = Session()

    try:
        # Verify query runs smoothly without 'no such column: evidence.explanation'
        legacy_ev = session.query(Evidence).filter(Evidence.id == "ev-legacy-1").first()
        assert legacy_ev is not None
        assert legacy_ev.explanation is None

        # Verify we can update explanation column
        legacy_ev.explanation = "Successfully migrated."
        session.commit()

        reloaded = session.query(Evidence).filter(Evidence.id == "ev-legacy-1").first()
        assert reloaded.explanation == "Successfully migrated."

    finally:
        session.close()
        eng.dispose()
        if os.path.exists(db_name):
            try:
                os.remove(db_name)
            except Exception:
                pass
