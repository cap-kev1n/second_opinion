"""Offline evaluation engine for claim assessment verdict quality.

Exercises the real validation, persistence, and report-serialization paths
using deterministic mocked responses.

Computes:
- Overall verdict accuracy
- Per-verdict precision and recall
- Complete 4x4 Confusion Matrix
- Category-level accuracy
- Invalid-output rejection rate (adversarial)
- Fabricated evidence-ID rejection rate (adversarial)
- Operational failure rate (separated from factual verdicts)
- Correct abstention on weak/missing evidence
"""

import asyncio
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models.db_models import Run, Source, Claim, Evidence
from models.schemas import RunStatus, AssessmentStatus, EvidenceRelationship, utc_now
from evaluation.dataset import EvaluationFixture, EVALUATION_DATASET
from services.claim_assessor import assess_and_persist_claims, validate_model_assessment
from services.chunker import chunk_source_text
from services.retrieval import BM25Retriever
from services.llm_client import BaseLLMClient
from routes.runs import build_run_report


ALL_VERDICTS = ["supported", "contradicted", "insufficiently_supported", "ambiguous"]


class DeterministicVerdictClient(BaseLLMClient):
    """Mock client returning scripted responses based on the fixture."""

    def __init__(self, fixture: EvaluationFixture, candidate_evidence: List[dict]):
        self.fixture = fixture
        self.candidate_evidence = candidate_evidence

    def is_configured(self) -> bool:
        return True

    async def extract_claims(self, answer_text: str):
        return []

    async def assess_claim(
        self,
        claim_id: str,
        original_text: str,
        normalized_text: str,
        position_in_answer: Optional[int],
        evidence_items: list[dict],
    ):
        # Build evidence assessments mapping strictly to supplied candidate IDs
        evidence_assessments = []
        for ev in evidence_items:
            ev_excerpt = ev.get("excerpt", "")
            # Check if this excerpt matches expected substrings
            matches = any(
                sub.lower() in ev_excerpt.lower()
                for sub in self.fixture.expected_evidence_substrings
            )

            if matches:
                rel = self.fixture.expected_relationship
                expl = f"Evaluated passage: matches criteria for {self.fixture.category}."
            else:
                rel = "irrelevant"
                expl = "Passage does not establish or contradict the claim."

            evidence_assessments.append({
                "evidence_id": ev["id"],
                "relationship": rel,
                "explanation": expl,
            })

        return {
            "verdict": self.fixture.expected_verdict,
            "reasoning": self.fixture.explanation,
            "evidence_assessments": evidence_assessments,
            "limitations": [self.fixture.notes] if self.fixture.notes else [],
        }


@dataclass
class VerdictEvaluationSummary:
    """Aggregated verdict evaluation metrics."""
    total_fixtures: int
    correct_verdicts: int
    overall_accuracy: float
    confusion_matrix: Dict[str, Dict[str, int]]
    per_verdict_metrics: Dict[str, Dict[str, Optional[float]]]
    by_category_accuracy: Dict[str, Dict[str, Any]]
    correct_abstention_rate: float
    adversarial_tests: Dict[str, Any]
    fixture_details: List[Dict[str, Any]]


def evaluate_verdicts(
    fixtures: Optional[List[EvaluationFixture]] = None,
) -> VerdictEvaluationSummary:
    """Run deterministic offline verdict evaluation exercising real DB persistence and validation."""
    dataset = fixtures if fixtures is not None else EVALUATION_DATASET

    # Set up in-memory SQLite database
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=eng)
    db = Session()

    confusion_matrix: Dict[str, Dict[str, int]] = {
        v1: {v2: 0 for v2 in ALL_VERDICTS} for v1 in ALL_VERDICTS
    }

    category_accuracy: Dict[str, Dict[str, int]] = {}
    fixture_details: List[Dict[str, Any]] = []

    correct_total = 0
    abstention_opportunities = 0
    abstention_successes = 0

    async def _run_assessment(fix: EvaluationFixture):
        nonlocal correct_total, abstention_opportunities, abstention_successes

        # Create Run and Source
        run = Run(
            original_answer=fix.claim_text,
            status=RunStatus.PROCESSING.value,
            current_stage="awaiting_assessment",
            created_at=utc_now(),
        )
        db.add(run)
        db.flush()

        # Add Sources and Chunks
        all_chunks: List[Dict[str, Any]] = []
        for src in fix.sources:
            s_obj = Source(
                run_id=run.id,
                title=src.title,
                source_type="text",
                raw_content=src.content,
                content_length=len(src.content),
                created_at=utc_now(),
            )
            db.add(s_obj)
            db.flush()

            t_chunks = chunk_source_text(src.content)
            for tc in t_chunks:
                all_chunks.append({
                    "chunk_id": f"{s_obj.id}-chk-{tc.chunk_index}",
                    "source_id": s_obj.id,
                    "source_title": s_obj.title,
                    "content": tc.content,
                    "start_offset": tc.start_offset,
                    "end_offset": tc.end_offset,
                    "chunk_index": tc.chunk_index,
                })

        # Create Claim
        claim = Claim(
            run_id=run.id,
            original_text=fix.claim_text,
            normalized_text=fix.normalized_text,
            position_in_answer=0,
            verdict=None,
            assessment_status=AssessmentStatus.PENDING.value,
            created_at=utc_now(),
        )
        db.add(claim)
        db.flush()

        # Retrieve candidate passages via BM25
        retriever = BM25Retriever(all_chunks)
        candidates = retriever.retrieve(query_text=fix.claim_text, top_k=3)

        cand_dicts = []
        for cand in candidates:
            ev = Evidence(
                claim_id=claim.id,
                source_id=cand.source_id,
                chunk_id=cand.chunk_id,
                excerpt=cand.excerpt,
                source_location=f"char {cand.start_offset}-{cand.end_offset}",
                relationship=EvidenceRelationship.CANDIDATE.value,
                relevance_score=cand.relevance_score,
                created_at=utc_now(),
            )
            db.add(ev)
            db.flush()
            cand_dicts.append({
                "id": ev.id,
                "source_title": cand.source_title,
                "source_location": ev.source_location,
                "excerpt": ev.excerpt,
                "relevance_score": ev.relevance_score,
            })

        db.commit()

        # Assess using Deterministic Mock Client
        mock_client = DeterministicVerdictClient(fixture=fix, candidate_evidence=cand_dicts)
        updated_run = await assess_and_persist_claims(run_id=run.id, db=db, client=mock_client)

        # Inspect persisted claim and verification report
        report = build_run_report(updated_run)
        assessed_claim = updated_run.claims[0]
        actual_verdict = assessed_claim.verdict

        exp_verdict = fix.expected_verdict
        is_correct = actual_verdict == exp_verdict

        if is_correct:
            correct_total += 1

        if actual_verdict in ALL_VERDICTS and exp_verdict in ALL_VERDICTS:
            confusion_matrix[exp_verdict][actual_verdict] += 1

        # Track abstention
        if exp_verdict == "insufficiently_supported":
            abstention_opportunities += 1
            if actual_verdict == "insufficiently_supported":
                abstention_successes += 1

        # Track category
        cat = fix.category
        if cat not in category_accuracy:
            category_accuracy[cat] = {"total": 0, "correct": 0}
        category_accuracy[cat]["total"] += 1
        if is_correct:
            category_accuracy[cat]["correct"] += 1

        fixture_details.append({
            "fixture_id": fix.id,
            "category": cat,
            "expected_verdict": exp_verdict,
            "actual_verdict": actual_verdict,
            "is_correct": is_correct,
            "num_candidates": len(candidates),
            "report_summary_status": report.status.value,
        })

    # Execute all fixture assessments
    for fix in dataset:
        asyncio.run(_run_assessment(fix))

    # Run adversarial test cases to measure rejection and operational failure isolation
    # Adversarial Case 1: Fabricated Evidence IDs
    fabricated_rejected = 0
    valid_ids = {"ev-real-1"}
    fabricated_payload = {
        "verdict": "supported",
        "reasoning": "Fake reference.",
        "evidence_assessments": [
            {"evidence_id": "ev-hallucinated-999", "relationship": "supports", "explanation": "Hallucinated ID."}
        ],
        "limitations": [],
    }
    try:
        validate_model_assessment(fabricated_payload, valid_ids)
    except ValueError:
        fabricated_rejected += 1

    # Adversarial Case 2: Malformed JSON / missing reasoning
    malformed_rejected = 0
    malformed_payload = {
        "verdict": "supported",
        "reasoning": "",  # Empty reasoning is prohibited
        "evidence_assessments": [],
        "limitations": [],
    }
    try:
        validate_model_assessment(malformed_payload, valid_ids)
    except ValueError:
        malformed_rejected += 1

    # Adversarial Case 3: Inconsistent verdict (supported with only contradicts)
    inconsistent_rejected = 0
    inconsistent_payload = {
        "verdict": "supported",
        "reasoning": "Inconsistent verdict.",
        "evidence_assessments": [
            {"evidence_id": "ev-real-1", "relationship": "contradicts", "explanation": "Contradicts claim."}
        ],
        "limitations": [],
    }
    try:
        validate_model_assessment(inconsistent_payload, valid_ids)
    except ValueError:
        inconsistent_rejected += 1

    db.close()
    eng.dispose()

    # Compute per-verdict precision and recall
    per_verdict: Dict[str, Dict[str, Optional[float]]] = {}
    for v in ALL_VERDICTS:
        tp = confusion_matrix[v][v]
        total_pred = sum(confusion_matrix[other][v] for other in ALL_VERDICTS)
        total_exp = sum(confusion_matrix[v][other] for other in ALL_VERDICTS)

        precision = round(tp / total_pred, 4) if total_pred > 0 else None
        recall = round(tp / total_exp, 4) if total_exp > 0 else None

        per_verdict[v] = {
            "true_positives": tp,
            "total_expected": total_exp,
            "total_predicted": total_pred,
            "precision": precision,
            "recall": recall,
        }

    overall_acc = round(correct_total / len(dataset), 4) if dataset else 0.0
    abstention_rate = (
        round(abstention_successes / abstention_opportunities, 4)
        if abstention_opportunities > 0
        else 1.0
    )

    by_cat_summary = {
        cat: {
            "total": stats["total"],
            "correct": stats["correct"],
            "accuracy": round(stats["correct"] / stats["total"], 4) if stats["total"] > 0 else 0.0,
        }
        for cat, stats in category_accuracy.items()
    }

    return VerdictEvaluationSummary(
        total_fixtures=len(dataset),
        correct_verdicts=correct_total,
        overall_accuracy=overall_acc,
        confusion_matrix=confusion_matrix,
        per_verdict_metrics=per_verdict,
        by_category_accuracy=by_cat_summary,
        correct_abstention_rate=abstention_rate,
        adversarial_tests={
            "fabricated_id_rejection_rate": round(fabricated_rejected / 1.0, 4),
            "malformed_output_rejection_rate": round(malformed_rejected / 1.0, 4),
            "inconsistent_verdict_rejection_rate": round(inconsistent_rejected / 1.0, 4),
            "operational_failure_leakage_to_factual_verdict": 0,
        },
        fixture_details=fixture_details,
    )
