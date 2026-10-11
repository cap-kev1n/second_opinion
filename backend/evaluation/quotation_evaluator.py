"""Quotation Auditing Evaluator for Second Opinion (Phase 7A).

Evaluates the deterministic and model-assisted quotation auditing pipeline
against the versioned benchmark dataset without making external network calls.
"""

from typing import Dict, Any, List
from dataclasses import dataclass, asdict
import json
import pymupdf

from models.schemas import QuoteMatchStatus
from models.db_models import Source
from services.quotation_auditor import (
    extract_candidate_quotations,
    audit_single_quotation_deterministic,
)
from services.pdf_ingestion import get_pdf_storage_dir, cleanup_pdf_file
from evaluation.quotation_dataset import (
    QUOTATION_EVALUATION_DATASET,
    QUOTATION_DATASET_VERSION,
    QuotationEvaluationFixture,
)


@dataclass
class QuotationEvaluationSummary:
    dataset_version: str
    total_fixtures: int
    correct_matches: int
    overall_accuracy: float
    confusion_matrix: Dict[str, Dict[str, int]]
    per_outcome_metrics: Dict[str, Dict[str, Any]]
    fixtures: List[Dict[str, Any]]


def create_synthetic_pdf_bytes(pages: List[str]) -> bytes:
    """Create in-memory PDF from text pages."""
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        if text.strip():
            page.insert_text((50, 72), text)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def evaluate_quotations(dataset: List[QuotationEvaluationFixture] = None) -> QuotationEvaluationSummary:
    """Evaluate quotation auditor across the benchmark dataset."""
    target_dataset = dataset if dataset is not None else QUOTATION_EVALUATION_DATASET

    outcomes = [
        QuoteMatchStatus.EXACT_MATCH.value,
        QuoteMatchStatus.NORMALIZED_MATCH.value,
        QuoteMatchStatus.ALTERED_QUOTE.value,
        QuoteMatchStatus.PARTIAL_MATCH.value,
        QuoteMatchStatus.UNVERIFIABLE.value,
    ]

    confusion_matrix: Dict[str, Dict[str, int]] = {
        exp: {pred: 0 for pred in outcomes} for exp in outcomes
    }

    correct_matches = 0
    fixture_results: List[Dict[str, Any]] = []
    created_pdf_source_ids: List[str] = []

    try:
        for fix in target_dataset:
            # Construct Source objects
            sources: List[Source] = []
            for s_fix in fix.sources:
                if s_fix.source_type == "pdf":
                    pdf_bytes = create_synthetic_pdf_bytes(s_fix.pages or [s_fix.content])
                    storage_dir = get_pdf_storage_dir()
                    pdf_path = storage_dir / f"{s_fix.id}.pdf"
                    with open(pdf_path, "wb") as f:
                        f.write(pdf_bytes)
                    created_pdf_source_ids.append(s_fix.id)

                    delimited = "\n\n".join(f"--- Page {i+1} ---\n{p}" for i, p in enumerate(s_fix.pages or [s_fix.content]))
                    src_obj = Source(
                        id=s_fix.id,
                        run_id="run-eval-quote",
                        title=s_fix.title,
                        source_type="pdf",
                        raw_content=delimited,
                        content_length=len(delimited),
                        page_count=len(s_fix.pages or [s_fix.content]),
                        extraction_metadata=json.dumps({"page_count": len(s_fix.pages or [])}),
                    )
                else:
                    src_obj = Source(
                        id=s_fix.id,
                        run_id="run-eval-quote",
                        title=s_fix.title,
                        source_type="text",
                        raw_content=s_fix.content,
                        content_length=len(s_fix.content),
                    )
                sources.append(src_obj)

            # Extract candidate quotes from fixture answer
            candidates = extract_candidate_quotations(fix.answer)

            # Find target candidate
            target_cand = next(
                (c for c in candidates if c.quotation_text == fix.target_quotation),
                candidates[0] if candidates else None,
            )

            if not target_cand:
                # If extraction failed to find candidate
                predicted = QuoteMatchStatus.UNVERIFIABLE.value
                match_method = "extraction_miss"
                differences = "Quotation not identified in answer"
            else:
                match_res = audit_single_quotation_deterministic(target_cand, sources)
                predicted = match_res.match_status.value
                match_method = match_res.match_method
                differences = match_res.differences

            expected = fix.expected_outcome.value
            if expected in confusion_matrix and predicted in confusion_matrix[expected]:
                confusion_matrix[expected][predicted] += 1

            is_correct = (expected == predicted)
            if is_correct:
                correct_matches += 1

            fixture_results.append({
                "fixture_id": fix.id,
                "category": fix.category,
                "quotation": fix.target_quotation,
                "expected": expected,
                "predicted": predicted,
                "is_correct": is_correct,
                "match_method": match_method,
                "differences": differences,
                "notes": fix.notes,
            })
    finally:
        for pid in created_pdf_source_ids:
            cleanup_pdf_file(pid)

    total = len(target_dataset)
    accuracy = (correct_matches / total) if total > 0 else 0.0

    # Calculate per-outcome precision and recall
    per_outcome_metrics: Dict[str, Dict[str, Any]] = {}
    for outcome in outcomes:
        tp = confusion_matrix[outcome][outcome]
        total_exp = sum(confusion_matrix[outcome][p] for p in outcomes)
        total_pred = sum(confusion_matrix[e][outcome] for e in outcomes)

        precision = (tp / total_pred) if total_pred > 0 else (1.0 if total_exp == 0 else 0.0)
        recall = (tp / total_exp) if total_exp > 0 else 1.0

        per_outcome_metrics[outcome] = {
            "total_expected": total_exp,
            "total_predicted": total_pred,
            "true_positives": tp,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
        }

    return QuotationEvaluationSummary(
        dataset_version=QUOTATION_DATASET_VERSION,
        total_fixtures=total,
        correct_matches=correct_matches,
        overall_accuracy=round(accuracy, 4),
        confusion_matrix=confusion_matrix,
        per_outcome_metrics=per_outcome_metrics,
        fixtures=fixture_results,
    )
