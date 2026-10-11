"""Claim extraction orchestration service.

Extracts atomic factual claims from an answer, validates them strictly,
and persists them to the database while managing the run lifecycle stages.
"""

from typing import List, Optional
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from models.db_models import Run, Claim
from models.schemas import RunStatus, AssessmentStatus, utc_now
from services.llm_client import BaseLLMClient, llm_service


async def extract_and_persist_claims(
    run_id: str,
    db: Session,
    client: Optional[BaseLLMClient] = None,
) -> List[Claim]:
    """Extract factual claims from the run's original answer and persist them.
    
    Manages run lifecycle:
    - Rejects concurrent extraction with 409 Conflict.
    - Returns existing claims if already completed (idempotent).
    - Transitions stage: pending -> extracting_claims -> awaiting_evidence (or failed).
    - Persists valid claims with verdict=None, assessment_status=pending.
    """
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Verification run '{run_id}' was not found.",
        )

    # Concurrency check: avoid duplicate execution
    if run.current_stage == "extracting_claims":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Claim extraction is already in progress for this run.",
        )

    # Idempotent check: if already completed, return existing claims without calling Gemini again
    # (handles runs with 0 claims as well)
    if run.current_stage == "awaiting_evidence":
        return run.claims

    # Atomic DB-level transition to prevent race conditions across concurrent workers/requests:
    # Only transitions to 'extracting_claims' if not already 'extracting_claims' or 'awaiting_evidence'
    rows_updated = (
        db.query(Run)
        .filter(
            Run.id == run_id,
            Run.current_stage.notin_(["extracting_claims", "awaiting_evidence"]),
        )
        .update(
            {
                Run.status: RunStatus.PROCESSING.value,
                Run.current_stage: "extracting_claims",
                Run.error_message: None,
            },
            synchronize_session="fetch",
        )
    )
    db.commit()

    if rows_updated == 0:
        db.refresh(run)
        if run.current_stage == "awaiting_evidence":
            return run.claims
        elif run.current_stage == "extracting_claims":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Claim extraction is already in progress for this run.",
            )

    active_client = client or llm_service

    try:
        # Call Gemini through the client interface
        extracted_items = await active_client.extract_claims(run.original_answer)

        # Clear any prior claims for this run (clean retry support)
        db.query(Claim).filter(Claim.run_id == run.id).delete()

        # Persist extracted claims in their original order
        persisted_claims: List[Claim] = []
        for idx, item in enumerate(extracted_items):
            orig_text = item["original_text"]
            norm_text = item["normalized_text"]

            pos = run.original_answer.find(orig_text)
            char_pos = pos if pos != -1 else idx

            new_claim = Claim(
                run_id=run.id,
                original_text=orig_text,
                normalized_text=norm_text,
                position_in_answer=char_pos,
                verdict=None,  # Crucial: Not yet assessed
                assessment_status=AssessmentStatus.PENDING.value,
                reasoning=None,
                limitations=None,
                created_at=utc_now(),
            )
            db.add(new_claim)
            persisted_claims.append(new_claim)

        # Update run lifecycle to awaiting_evidence
        run.status = RunStatus.PROCESSING.value
        run.current_stage = "awaiting_evidence"
        run.error_message = None
        db.commit()
        db.refresh(run)

        return run.claims

    except Exception as e:
        db.rollback()
        # Cleanly record failure state on the run record
        err_msg = str(e)
        # Sanitize error message to ensure no potential secrets are stored
        sanitized_msg = err_msg.replace(getattr(active_client, "_api_key", ""), "[REDACTED]") if hasattr(active_client, "_api_key") and active_client._api_key else err_msg

        try:
            failed_run = db.query(Run).filter(Run.id == run_id).first()
            if failed_run:
                failed_run.status = RunStatus.FAILED.value
                failed_run.current_stage = "failed"
                failed_run.error_message = f"Claim extraction failed: {sanitized_msg}"
                db.commit()
        except Exception:
            pass

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Claim extraction failed: {sanitized_msg}",
        )
