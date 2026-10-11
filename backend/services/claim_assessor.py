"""Claim assessment orchestration service.

Evaluates extracted claims strictly against retrieved source candidate passages,
validates model responses against DB relationships and consistency rules,
and persists verdicts and evidence relationships while maintaining the run lifecycle.
"""

import asyncio
from typing import List, Dict, Any, Optional, Set
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from models.db_models import Run, Claim, Evidence
from models.schemas import (
    RunStatus,
    AssessmentStatus,
    Verdict,
    EvidenceRelationship,
    utc_now,
)
from services.llm_client import BaseLLMClient, llm_service


def validate_model_assessment(
    raw_result: Dict[str, Any],
    valid_evidence_ids: Set[str],
) -> Dict[str, Any]:
    """Strictly validate the structured assessment returned by the LLM.

    Validation Rules:
    1. Verdict must be one of the four allowed Verdict enum values.
    2. Every referenced evidence_id must belong strictly to this claim and run.
    3. Evidence IDs must not be duplicated.
    4. Explanations must be non-empty.
    5. Logical consistency:
       - 'supported' requires at least one 'supports' or 'partially_supports' evidence item.
       - 'contradicted' requires at least one 'contradicts' evidence item.
       - If all evidence items are 'irrelevant', verdict must be 'insufficiently_supported'.
    """
    if not isinstance(raw_result, dict):
        raise ValueError("Assessment result must be a JSON object dictionary.")

    raw_verdict = raw_result.get("verdict")
    allowed_verdicts = {v.value for v in Verdict}
    if raw_verdict not in allowed_verdicts:
        raise ValueError(
            f"Invalid verdict '{raw_verdict}'. Allowed verdicts: {allowed_verdicts}"
        )

    reasoning = (raw_result.get("reasoning") or "").strip()
    if not reasoning:
        raise ValueError("Assessment response must include non-empty reasoning.")

    raw_evidence_assessments = raw_result.get("evidence_assessments") or []
    if not isinstance(raw_evidence_assessments, list):
        raise ValueError("evidence_assessments must be a list.")

    seen_evidence_ids = set()
    validated_evidence_assessments = []

    allowed_relationships = {r.value for r in EvidenceRelationship}

    for item in raw_evidence_assessments:
        if not isinstance(item, dict):
            raise ValueError("Each evidence assessment must be a dictionary.")

        ev_id = item.get("evidence_id")
        if not ev_id or not isinstance(ev_id, str):
            raise ValueError("Missing or invalid evidence_id in assessment item.")

        if ev_id not in valid_evidence_ids:
            raise ValueError(
                f"Model returned unsupplied evidence ID '{ev_id}'. "
                "Only provided candidate evidence IDs are permitted."
            )

        if ev_id in seen_evidence_ids:
            raise ValueError(f"Duplicate evidence ID '{ev_id}' in model assessment.")
        seen_evidence_ids.add(ev_id)

        rel = (item.get("relationship") or "").strip().lower()
        if rel not in allowed_relationships:
            raise ValueError(
                f"Invalid evidence relationship '{rel}' for evidence '{ev_id}'. "
                f"Allowed: {allowed_relationships}"
            )

        expl = (item.get("explanation") or "").strip()
        if not expl:
            raise ValueError(f"Missing explanation for evidence ID '{ev_id}'.")

        validated_evidence_assessments.append({
            "evidence_id": ev_id,
            "relationship": rel,
            "explanation": expl,
        })

    # Logical consistency verification
    relationships = [item["relationship"] for item in validated_evidence_assessments]

    has_support = any(r == EvidenceRelationship.SUPPORTS.value for r in relationships)
    has_partial_support = any(r == EvidenceRelationship.PARTIALLY_SUPPORTS.value for r in relationships)
    has_contradiction = any(r == EvidenceRelationship.CONTRADICTS.value for r in relationships)
    has_conflicting = any(r == EvidenceRelationship.CONFLICTING.value for r in relationships)
    all_irrelevant = bool(relationships) and all(r == EvidenceRelationship.IRRELEVANT.value for r in relationships)

    # Invariant 1: If all evidence items are irrelevant, verdict MUST be 'insufficiently_supported'
    if all_irrelevant and raw_verdict != Verdict.INSUFFICIENTLY_SUPPORTED.value:
        raise ValueError(
            "Inconsistent verdict: When all evaluated evidence items are 'irrelevant', "
            "verdict must be 'insufficiently_supported'."
        )

    # Invariant 2: Conflicting support and contradiction cannot be unconditionally supported or contradicted
    has_mixed_conflict = (has_support or has_partial_support) and has_contradiction
    if has_mixed_conflict and raw_verdict in [Verdict.SUPPORTED.value, Verdict.CONTRADICTED.value]:
        raise ValueError(
            "Inconsistent verdict: Candidate evidence contains direct conflict between supporting "
            "and contradicting passages. Conflicting evidence must be resolved as 'ambiguous'."
        )

    if raw_verdict == Verdict.SUPPORTED.value:
        if has_contradiction or has_conflicting:
            raise ValueError(
                "Inconsistent verdict: Claim marked as 'supported' but candidate evidence contains "
                "contradictory or conflicting passages. Conflicting evidence requires 'ambiguous'."
            )
        if not has_support:
            raise ValueError(
                "Inconsistent verdict: Claim marked as 'supported' requires at least one directly supporting ('supports') evidence item."
            )

    elif raw_verdict == Verdict.CONTRADICTED.value:
        if has_support or has_conflicting:
            raise ValueError(
                "Inconsistent verdict: Claim marked as 'contradicted' but candidate evidence contains "
                "supporting or conflicting passages. Conflicting evidence requires 'ambiguous'."
            )
        if not has_contradiction:
            raise ValueError(
                "Inconsistent verdict: Claim marked as 'contradicted' requires at least one directly contradicting ('contradicts') evidence item."
            )

    elif raw_verdict == Verdict.AMBIGUOUS.value:
        if all_irrelevant:
            raise ValueError(
                "Inconsistent verdict: Claim cannot be 'ambiguous' when all evidence is irrelevant. "
                "Must be 'insufficiently_supported'."
            )

    elif raw_verdict == Verdict.INSUFFICIENTLY_SUPPORTED.value:
        if has_contradiction and not (has_support or has_partial_support or has_conflicting):
            raise ValueError(
                "Inconsistent verdict: Evidence directly contradicts the claim without supporting or conflicting passages; "
                "verdict must be 'contradicted'."
            )

    limitations = raw_result.get("limitations") or []
    if isinstance(limitations, list):
        clean_limitations = [str(lim).strip() for lim in limitations if str(lim).strip()]
    else:
        clean_limitations = [str(limitations).strip()] if str(limitations).strip() else []

    return {
        "verdict": raw_verdict,
        "reasoning": reasoning,
        "evidence_assessments": validated_evidence_assessments,
        "limitations": clean_limitations,
    }


async def assess_single_claim(
    claim: Claim,
    candidates: List[Evidence],
    active_client: BaseLLMClient,
    force_reassess: bool = False,
) -> Dict[str, Any]:
    """Assess a single claim against its candidate evidence items."""
    # Idempotency: if already assessed and not forcing reassessment, preserve result
    if (
        not force_reassess
        and claim.assessment_status == AssessmentStatus.ASSESSED.value
        and claim.verdict is not None
    ):
        return {
            "status": "skipped",
            "verdict": claim.verdict,
            "reasoning": claim.reasoning,
            "limitations": claim.limitations,
            "assessments": [],
        }

    # Case A: No candidate evidence items exist
    # RULE: Do NOT call Gemini! Return 'insufficiently_supported' immediately.
    if len(candidates) == 0:
        return {
            "status": "success",
            "verdict": Verdict.INSUFFICIENTLY_SUPPORTED.value,
            "reasoning": (
                "No relevant candidate passages were retrieved from the user-supplied reference sources "
                "to evaluate this claim. In accordance with strict evidence grounding, missing evidence "
                "does not establish that the claim is false."
            ),
            "limitations": ["No candidate evidence was found in the supplied reference documents."],
            "assessments": [],
        }

    # Case B: Candidate evidence exists -> Invoke LLM with strict evidence grounding
    evidence_payload = [
        {
            "id": ev.id,
            "source_title": ev.source.title if ev.source else "Source",
            "source_location": ev.source_location,
            "excerpt": ev.excerpt,
            "relevance_score": ev.relevance_score,
        }
        for ev in candidates
    ]

    valid_evidence_ids = {ev.id for ev in candidates}

    try:
        raw_output = await active_client.assess_claim(
            claim_id=claim.id,
            original_text=claim.original_text,
            normalized_text=claim.normalized_text,
            position_in_answer=claim.position_in_answer,
            evidence_items=evidence_payload,
        )

        # Strictly validate model response
        validated = validate_model_assessment(raw_output, valid_evidence_ids)
        return {
            "status": "success",
            "verdict": validated["verdict"],
            "reasoning": validated["reasoning"],
            "limitations": validated["limitations"],
            "assessments": validated["evidence_assessments"],
        }

    except Exception as e:
        err_msg = str(e)
        return {
            "status": "failed",
            "error": err_msg,
        }


# Global set tracking actively running assessments in this process to prevent concurrency races
_active_assessments: Set[str] = set()


async def assess_and_persist_claims(
    run_id: str,
    db: Session,
    client: Optional[BaseLLMClient] = None,
    force_reassess: bool = False,
    concurrency_limit: int = 3,
) -> Run:
    """Assess all claims for a run against candidate evidence and persist results.

    Guarantees:
    - Evidence retrieval must be completed prior to assessment.
    - Concurrency protection: returns 409 Conflict if already assessing.
    - Zero candidate evidence skips the LLM and assigns insufficiently_supported.
    - Operational errors produce assessment_status=FAILED, never a factual verdict.
    - DB transactions are not held open during external LLM calls.
    - Idempotent on repeated calls unless force_reassess is requested.
    - Safe recovery from stuck abandoned states when no active worker is processing.
    """
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Verification run '{run_id}' was not found.",
        )

    # Concurrency check 1: Disallow assessment while previous stages are running
    if run.current_stage in ["extracting_claims", "retrieving_evidence"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot assess claims: {run.current_stage.replace('_', ' ').capitalize()} is currently in progress.",
        )

    # Concurrency check 2: Active in-process execution check
    if run_id in _active_assessments:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Claim assessment is actively in progress for this run.",
        )

    # Concurrency check 3: If in assessing_claims without explicit force_reassess, reject as conflict
    if run.current_stage == "assessing_claims" and not force_reassess:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Claim assessment is already in progress for this run.",
        )

    # Pre-condition: Evidence retrieval must be completed (or recovering with force_reassess from abandoned state)
    allowed_stages = ["awaiting_assessment", "assessment_completed", "assessment_partial", "assessment_failed"]
    if force_reassess:
        allowed_stages.append("assessing_claims")

    if run.current_stage not in allowed_stages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Evidence retrieval must be completed before assessing claims.",
        )

    # Atomic DB-level transition to assessing_claims
    rows_updated = (
        db.query(Run)
        .filter(
            Run.id == run_id,
            Run.current_stage.in_(allowed_stages),
        )
        .update(
            {
                Run.status: RunStatus.PROCESSING.value,
                Run.current_stage: "assessing_claims",
                Run.error_message: None,
            },
            synchronize_session="fetch",
        )
    )
    db.commit()

    if rows_updated == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Claim assessment is already in progress for this run.",
        )

    _active_assessments.add(run_id)

    try:
        active_client = client or llm_service

        # Handle zero claims case immediately
        if len(run.claims) == 0:
            run.status = RunStatus.COMPLETED.value
            run.current_stage = "assessment_completed"
            run.completed_at = utc_now()
            db.commit()
            db.refresh(run)
            return run

        # Prepare claim evaluation tasks
        claims_to_assess = list(run.claims)
        semaphore = asyncio.Semaphore(concurrency_limit)

        async def evaluate_claim_with_semaphore(claim_obj: Claim):
            # Fast-path for already assessed claims when not forcing reassessment
            if (
                not force_reassess
                and claim_obj.assessment_status == AssessmentStatus.ASSESSED.value
                and claim_obj.verdict is not None
            ):
                return claim_obj.id, {
                    "status": "skipped",
                    "verdict": claim_obj.verdict,
                    "reasoning": claim_obj.reasoning,
                    "limitations": claim_obj.limitations,
                    "assessments": [],
                }

            cands = list(claim_obj.evidence_items)
            async with semaphore:
                result = await assess_single_claim(
                    claim=claim_obj,
                    candidates=cands,
                    active_client=active_client,
                    force_reassess=force_reassess,
                )
                return claim_obj.id, result

        # Execute assessments concurrently with bounded parallelism
        evaluation_results = await asyncio.gather(
            *(evaluate_claim_with_semaphore(c) for c in claims_to_assess)
        )

        # Persist validated assessments within a clean database transaction
        try:
            results_by_id = dict(evaluation_results)
            any_failures = False
            assessed_count = 0

            for claim in run.claims:
                eval_data = results_by_id.get(claim.id)
                if not eval_data:
                    continue

                status_str = eval_data.get("status")

                if status_str == "skipped":
                    assessed_count += 1
                    continue

                elif status_str == "success":
                    claim.verdict = eval_data["verdict"]
                    claim.assessment_status = AssessmentStatus.ASSESSED.value
                    claim.reasoning = eval_data["reasoning"]
                    lims = eval_data.get("limitations") or []
                    claim.limitations = "; ".join(lims) if lims else None

                    # Update individual evidence items with validated relationships and explanations
                    assessment_map = {
                        item["evidence_id"]: item for item in eval_data.get("assessments", [])
                    }
                    for ev in claim.evidence_items:
                        if ev.id in assessment_map:
                            ev.relationship = assessment_map[ev.id]["relationship"]
                            ev.explanation = assessment_map[ev.id]["explanation"]
                        else:
                            ev.relationship = EvidenceRelationship.IRRELEVANT.value
                            ev.explanation = "Passage not cited as supportive or contradictory."

                    assessed_count += 1

                elif status_str == "failed":
                    any_failures = True
                    claim.verdict = None  # CRITICAL INVARIANT: Operational failure is NEVER a factual verdict
                    claim.assessment_status = AssessmentStatus.FAILED.value
                    claim.reasoning = f"Operational assessment error: {eval_data.get('error', 'Unknown error')}"
                    claim.limitations = "Assessment could not be completed."
                    # Reset evidence items so stale relationships from prior runs do not survive
                    for ev in claim.evidence_items:
                        ev.relationship = EvidenceRelationship.CANDIDATE.value
                        ev.explanation = None

            # Update run lifecycle based on overall assessment outcome
            if not any_failures:
                run.status = RunStatus.COMPLETED.value
                run.current_stage = "assessment_completed"
                run.completed_at = utc_now()
                run.error_message = None
            elif assessed_count > 0:
                run.status = RunStatus.PROCESSING.value
                run.current_stage = "assessment_partial"
                run.error_message = "Some claims could not be assessed due to operational errors."
            else:
                run.status = RunStatus.FAILED.value
                run.current_stage = "assessment_failed"
                run.error_message = "All claims failed operational assessment."

            db.commit()
            db.refresh(run)
            return run

        except Exception as e:
            db.rollback()
            try:
                failed_run = db.query(Run).filter(Run.id == run_id).first()
                if failed_run:
                    failed_run.status = RunStatus.FAILED.value
                    failed_run.current_stage = "assessment_failed"
                    failed_run.error_message = f"Persistence error during assessment: {str(e)}"
                    db.commit()
            except Exception:
                pass

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to persist claim assessments: {str(e)}",
            )

    finally:
        _active_assessments.discard(run_id)
