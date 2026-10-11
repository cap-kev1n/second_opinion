"""Tests for Pydantic API schemas and contract invariants."""

from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from models.schemas import (
    Verdict,
    RunStatus,
    AssessmentStatus,
    SourceProcessingStatus,
    EvidenceRelationship,
    SourceType,
    ClaimResponse,
    EvidenceResponse,
    ProcessingSummary,
    VerificationReportResponse,
    RunCreateRequest,
    SourceCreateRequest,
    utc_now,
)


def test_invalid_verdict_enum_rejected():
    """Verify that unsupported verdict strings are rejected by Pydantic."""
    with pytest.raises(ValidationError):
        ClaimResponse(
            id="clm-1",
            run_id="run-1",
            original_text="Some statement",
            normalized_text="Some normalized statement",
            verdict="true",  # Invalid enum value! Must be one of 4 verdicts or None
            assessment_status=AssessmentStatus.ASSESSED,
        )


def test_claim_with_no_evidence_is_valid():
    """Verify that a claim can legitimately have an empty evidence list."""
    claim = ClaimResponse(
        id="clm-1",
        run_id="run-1",
        original_text="The sky is blue on Mars.",
        normalized_text="The sky is blue on Mars.",
        verdict=Verdict.INSUFFICIENTLY_SUPPORTED,
        assessment_status=AssessmentStatus.ASSESSED,
        reasoning="No provided source discusses atmospheric colors on Mars.",
        evidence=[],  # No evidence found
    )
    assert len(claim.evidence) == 0
    assert claim.verdict == Verdict.INSUFFICIENTLY_SUPPORTED


def test_assessment_failure_distinguished_from_verdict():
    """Operational assessment failure must not be conflated with a factual verdict.
    
    A processing failure is NOT a verdict of contradiction or falsity.
    """
    failed_claim = ClaimResponse(
        id="clm-failed",
        run_id="run-1",
        original_text="Complex statement.",
        normalized_text="Complex statement.",
        verdict=None,  # No verdict because assessment failed
        assessment_status=AssessmentStatus.FAILED,
        reasoning="LLM assessment service encountered a timeout.",
    )
    assert failed_claim.assessment_status == AssessmentStatus.FAILED
    assert failed_claim.verdict is None


def test_report_schema_handles_mixed_claims_and_no_evidence():
    """Verify full verification report serialization with various claim states."""
    report = VerificationReportResponse(
        run_id="test-run-123",
        status=RunStatus.COMPLETED,
        original_answer="Original AI answer unchanged.",
        summary=ProcessingSummary(
            total_claims=2,
            supported=1,
            insufficiently_supported=1,
            contradicted=0,
            ambiguous=0,
            assessment_failures=0,
            sources_processed=1,
            sources_failed=0,
            coverage_note="1 claim lacked evidence in supplied sources.",
        ),
        claims=[
            ClaimResponse(
                id="c-1",
                run_id="test-run-123",
                original_text="Claim supported.",
                normalized_text="Claim supported.",
                verdict=Verdict.SUPPORTED,
                assessment_status=AssessmentStatus.ASSESSED,
                reasoning="Direct match in source.",
                evidence=[
                    EvidenceResponse(
                        id="ev-1",
                        claim_id="c-1",
                        source_id="src-1",
                        source_title="Document A",
                        excerpt="Exact text supporting claim.",
                        source_location="page 1",
                        relationship=EvidenceRelationship.SUPPORTS,
                        relevance_score=0.95,
                    )
                ],
            ),
            ClaimResponse(
                id="c-2",
                run_id="test-run-123",
                original_text="Claim with zero evidence.",
                normalized_text="Claim with zero evidence.",
                verdict=Verdict.INSUFFICIENTLY_SUPPORTED,
                assessment_status=AssessmentStatus.ASSESSED,
                reasoning="Missing evidence in supplied sources.",
                evidence=[],  # Crucial requirement: empty evidence supported
            ),
        ],
        quote_audits=[],
        sources=[],
        created_at=utc_now(),
    )

    assert len(report.claims) == 2
    assert report.claims[1].evidence == []
    assert report.claims[1].verdict == Verdict.INSUFFICIENTLY_SUPPORTED


def test_run_create_request_validation():
    """Verify input validation rules for run creation."""
    # Empty answer should be rejected (min_length=5)
    with pytest.raises(ValidationError):
        RunCreateRequest(
            answer="abc",
            sources=[SourceCreateRequest(title="Title", source_type=SourceType.TEXT, content="Text")],
        )

    # Empty sources list should be rejected (min_length=1)
    with pytest.raises(ValidationError):
        RunCreateRequest(
            answer="This is a valid test answer to verify.",
            sources=[],
        )
