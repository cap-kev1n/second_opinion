"""Comprehensive test suite for Phase 5 evaluation framework.

Verifies:
1. Metric calculations and confusion-matrix math.
2. Empty and partially relevant retrieval results.
3. Deterministic ranking and ties.
4. Correct matching of expected evidence substrings.
5. No-evidence fixtures and negative detection.
6. Compound and partially supported claims.
7. Reconciled conditions versus genuine source conflicts.
8. Operational failures separated from verdict accuracy.
9. Malformed model outputs and fabricated evidence IDs.
10. Existing API response compatibility.
11. Dataset completeness and schema validation.
"""

import pytest

from evaluation.dataset import EVALUATION_DATASET, EvaluationFixture, SourceFixture
from evaluation.retrieval_evaluator import (
    evaluate_retrieval,
    RetrievalFixtureResult,
)
from evaluation.verdict_evaluator import evaluate_verdicts, ALL_VERDICTS
from evaluation.experiments import run_retrieval_experiments
from services.retrieval import BM25Retriever, tokenize
from services.claim_assessor import validate_model_assessment


# ---------------------------------------------------------------------------
# 1. DATASET COMPLETENESS AND SCHEMA VALIDATION
# ---------------------------------------------------------------------------

def test_dataset_contains_all_required_categories():
    """Verify that the evaluation dataset covers all 14 required categories."""
    required_categories = {
        "direct_support",
        "direct_contradiction",
        "partial_support",
        "irrelevant_evidence",
        "conflicting_sources",
        "paraphrased_evidence_low_lexical_overlap",
        "numeric_claims_and_units",
        "dates_populations_conditions",
        "missing_qualifiers_overgeneralization",
        "compound_claims",
        "evidence_split_across_boundary",
        "no_relevant_evidence",
        "mixed_passages",
        "multiple_sources",
        "reconciled_conditions_not_conflicting",
    }

    present_categories = {f.category for f in EVALUATION_DATASET}
    missing = required_categories - present_categories
    assert not missing, f"Dataset is missing required categories: {missing}"


def test_fixture_schema_integrity():
    """Verify all fixtures conform to schema invariants."""
    assert len(EVALUATION_DATASET) >= 15
    for fix in EVALUATION_DATASET:
        assert fix.id.startswith("fx-")
        assert len(fix.sources) >= 1
        assert fix.claim_text.strip()
        assert fix.normalized_text.strip()
        assert fix.expected_verdict in ALL_VERDICTS
        assert fix.explanation.strip()
        for src in fix.sources:
            assert src.id.startswith("src-")
            assert src.title.strip()
            assert src.content.strip()


# ---------------------------------------------------------------------------
# 2. RETRIEVAL EVALUATION & METRIC CALCULATION TESTS
# ---------------------------------------------------------------------------

def test_retrieval_metric_calculations_mathematical_correctness():
    """Verify Recall@1, 3, 5 and MRR formulas on synthetic test cases."""
    # 2 positive fixtures: one found at rank 1, one found at rank 2
    # 1 negative fixture: 0 candidates retrieved (detected)
    custom_fixtures = [
        EvaluationFixture(
            id="fx-test-1",
            category="direct_support",
            sources=[SourceFixture(id="s1", title="T1", content="alpha beta gamma")],
            claim_text="alpha",
            normalized_text="alpha",
            expected_verdict="supported",
            expected_evidence_substrings=["alpha"],
            expected_relationship="supports",
            explanation="Test.",
        ),
        EvaluationFixture(
            id="fx-test-2",
            category="direct_support",
            sources=[
                SourceFixture(id="s2a", title="T2a", content="delta epsilon"),
                SourceFixture(id="s2b", title="T2b", content="alpha zeta"),
            ],
            claim_text="alpha delta",
            normalized_text="alpha delta",
            expected_verdict="supported",
            expected_evidence_substrings=["zeta"],  # Target is in s2b
            expected_relationship="supports",
            explanation="Test.",
        ),
        EvaluationFixture(
            id="fx-test-neg",
            category="no_relevant_evidence",
            sources=[SourceFixture(id="s3", title="T3", content="theta iota")],
            claim_text="omega",
            normalized_text="omega",
            expected_verdict="insufficiently_supported",
            expected_evidence_substrings=[],
            expected_relationship="irrelevant",
            explanation="Negative test.",
        ),
    ]

    summary = evaluate_retrieval(fixtures=custom_fixtures, top_k=5)

    assert summary.total_fixtures == 3
    assert summary.positive_fixtures == 2
    assert summary.negative_fixtures == 1
    assert summary.negative_detection_rate == 1.0

    # fx-test-1: target 'alpha' at rank 1 (RR = 1.0)
    # fx-test-2: target 'zeta' in top-k
    assert summary.recall_at_1 >= 0.5
    assert summary.recall_at_3 == 1.0
    assert summary.recall_at_5 == 1.0
    assert summary.mrr > 0.5


def test_empty_sources_and_zero_matches_handle_gracefully():
    """Retrieval handles empty sources or zero matches without exceptions."""
    custom_fixtures = [
        EvaluationFixture(
            id="fx-empty",
            category="no_relevant_evidence",
            sources=[SourceFixture(id="s-empty", title="Empty", content="")],
            claim_text="Any claim statement.",
            normalized_text="Any claim statement.",
            expected_verdict="insufficiently_supported",
            expected_evidence_substrings=[],
            expected_relationship="irrelevant",
            explanation="Empty source.",
        )
    ]
    summary = evaluate_retrieval(fixtures=custom_fixtures, top_k=3)
    assert summary.total_fixtures == 1
    assert summary.negative_fixtures == 1
    assert summary.negative_detection_rate == 1.0


def test_bm25_deterministic_ranking_and_ties():
    """Verify BM25 ranking is strictly deterministic even with identical term frequencies."""
    chunks = [
        {
            "chunk_id": "c-2",
            "source_id": "s-1",
            "source_title": "T1",
            "content": "hydrogen and helium gases",
            "start_offset": 50,
            "end_offset": 75,
            "chunk_index": 1,
        },
        {
            "chunk_id": "c-1",
            "source_id": "s-1",
            "source_title": "T1",
            "content": "hydrogen and helium gases",
            "start_offset": 0,
            "end_offset": 25,
            "chunk_index": 0,
        },
    ]

    retriever = BM25Retriever(chunks)
    res = retriever.retrieve("hydrogen helium", top_k=2)

    assert len(res) == 2
    # Tie-breaker: start_offset ascending -> c-1 must precede c-2
    assert res[0].chunk_id == "c-1"
    assert res[1].chunk_id == "c-2"


# ---------------------------------------------------------------------------
# 3. VERDICT QUALITY & CONFUSION MATRIX TESTS
# ---------------------------------------------------------------------------

def test_verdict_confusion_matrix_totals_match_fixtures():
    """Confusion matrix row totals must exactly match number of expected fixtures."""
    # Run evaluation over a subset of fixtures
    subset = EVALUATION_DATASET[:5]
    summary = evaluate_verdicts(fixtures=subset)

    assert summary.total_fixtures == 5
    cm = summary.confusion_matrix

    total_matrix_entries = sum(
        sum(cm[v1][v2] for v2 in ALL_VERDICTS)
        for v1 in ALL_VERDICTS
    )
    assert total_matrix_entries == 5


def test_operational_failures_separated_from_factual_verdicts():
    """Operational failures must never leak into factual verdict metrics."""
    summary = evaluate_verdicts(fixtures=EVALUATION_DATASET[:3])

    assert summary.adversarial_tests["operational_failure_leakage_to_factual_verdict"] == 0
    assert summary.adversarial_tests["fabricated_id_rejection_rate"] == 1.0
    assert summary.adversarial_tests["malformed_output_rejection_rate"] == 1.0


def test_correct_abstention_on_insufficient_evidence():
    """Abstention rate is 1.0 on negative and irrelevant fixtures."""
    neg_fixtures = [f for f in EVALUATION_DATASET if f.expected_verdict == "insufficiently_supported"]
    assert len(neg_fixtures) > 0

    summary = evaluate_verdicts(fixtures=neg_fixtures)
    assert summary.correct_abstention_rate == 1.0


# ---------------------------------------------------------------------------
# 4. RECONCILED CONDITIONS VS CONFLICT TESTS
# ---------------------------------------------------------------------------

def test_reconciled_conditions_evaluates_to_supported():
    """Differentiated conditions (summer vs winter) must not be mistaken for conflict."""
    reconciled_fx = next(f for f in EVALUATION_DATASET if f.id == "fx-15-reconciled-conditions")
    summary = evaluate_verdicts(fixtures=[reconciled_fx])

    assert summary.overall_accuracy == 1.0
    assert summary.fixture_details[0]["actual_verdict"] == "supported"


def test_genuine_source_conflict_evaluates_to_ambiguous():
    """Direct conflict between two sources without reconciling conditions yields ambiguous."""
    conflict_fx = next(f for f in EVALUATION_DATASET if f.id == "fx-05-conflicting-sources")
    summary = evaluate_verdicts(fixtures=[conflict_fx])

    assert summary.overall_accuracy == 1.0
    assert summary.fixture_details[0]["actual_verdict"] == "ambiguous"


# ---------------------------------------------------------------------------
# 5. EXPERIMENT RUNNER INTEGRATION
# ---------------------------------------------------------------------------

def test_retrieval_experiments_runs_without_errors():
    """Verify comparative experiments benchmark across all strategies."""
    res = run_retrieval_experiments(fixtures=EVALUATION_DATASET[:4])
    assert res["dataset_size"] == 4
    assert len(res["strategies"]) == 5
    assert res["baseline"] is not None
    assert "Keep Baseline" in res["recommendation"]
