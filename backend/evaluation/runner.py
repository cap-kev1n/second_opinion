"""Master CLI runner for Second Opinion Phase 5 evaluation.

Executes retrieval evaluation, verdict evaluation, and comparative experiments,
generating both a machine-readable JSON summary and a detailed Markdown report.

Usage:
    python -m evaluation.runner
"""

import json
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import asdict
from typing import Optional

from evaluation.dataset import EVALUATION_DATASET, DATASET_VERSION
from evaluation.retrieval_evaluator import evaluate_retrieval
from evaluation.verdict_evaluator import evaluate_verdicts
from evaluation.experiments import run_retrieval_experiments
from evaluation.quotation_dataset import QUOTATION_EVALUATION_DATASET, QUOTATION_DATASET_VERSION
from evaluation.quotation_evaluator import evaluate_quotations


def generate_markdown_report(
    dataset_version: str,
    retrieval_summary: dict,
    verdict_summary: dict,
    experiments_summary: dict,
    quotation_summary: Optional[dict] = None,
) -> str:
    """Format full evaluation metrics into a publication-ready Markdown report."""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Format Confusion Matrix
    cm = verdict_summary["confusion_matrix"]
    cm_rows = []
    for exp_v in ["supported", "contradicted", "insufficiently_supported", "ambiguous"]:
        row = f"| **{exp_v}** | {cm[exp_v]['supported']} | {cm[exp_v]['contradicted']} | {cm[exp_v]['insufficiently_supported']} | {cm[exp_v]['ambiguous']} |"
        cm_rows.append(row)
    cm_table = "\n".join(cm_rows)

    # Format Per-Verdict Metrics
    pvm = verdict_summary["per_verdict_metrics"]
    pvm_rows = []
    for v, stats in pvm.items():
        prec_str = f"{stats['precision']:.4f}" if stats['precision'] is not None else "N/A"
        rec_str = f"{stats['recall']:.4f}" if stats['recall'] is not None else "N/A"
        pvm_rows.append(
            f"| `{v}` | {stats['total_expected']} | {stats['total_predicted']} | {stats['true_positives']} | {prec_str} | {rec_str} |"
        )
    pvm_table = "\n".join(pvm_rows)

    # Format Strategy Comparison Table
    strat_rows = []
    for s in experiments_summary["strategies"]:
        strat_rows.append(
            f"| **{s['strategy']}** | {s['config']['chunk_size']} / {s['config']['chunk_overlap']} | {s['config']['top_k']} | {s['recall_at_1']:.4f} | {s['recall_at_3']:.4f} | {s['recall_at_5']:.4f} | {s['mrr']:.4f} | {s['negative_detection_rate']:.4f} |"
        )
    strat_table = "\n".join(strat_rows)

    # Format Retrieval Category Breakdown
    cat_rows = []
    for cat, stats in retrieval_summary["by_category"].items():
        cat_rows.append(
            f"| `{cat}` | {stats['total_fixtures']} | {stats['positive_fixtures']} | {stats['recall_at_1']:.4f} | {stats['recall_at_3']:.4f} | {stats['mrr']:.4f} |"
        )
    cat_table = "\n".join(cat_rows)

    # Format Quotation Auditing Table (if present)
    quote_section = ""
    if quotation_summary:
        q_cm = quotation_summary["confusion_matrix"]
        q_pvm = quotation_summary["per_outcome_metrics"]
        q_rows = []
        for out, stats in q_pvm.items():
            prec_str = f"{stats['precision']:.4f}" if stats['precision'] is not None else "N/A"
            rec_str = f"{stats['recall']:.4f}" if stats['recall'] is not None else "N/A"
            q_rows.append(
                f"| `{out}` | {stats['total_expected']} | {stats['total_predicted']} | {stats['true_positives']} | {prec_str} | {rec_str} |"
            )
        q_table = "\n".join(q_rows)

        quote_section = f"""
---

## 5. Quotation Auditing Quality Evaluation (Phase 7A)

- **Dataset Version:** `{quotation_summary['dataset_version']}` ({quotation_summary['total_fixtures']} fixtures)
- **Overall Quotation Accuracy:** **{quotation_summary['overall_accuracy'] * 100:.1f}%** ({quotation_summary['correct_matches']}/{quotation_summary['total_fixtures']})

### Per-Outcome Breakdown
| Outcome Class | Expected | Predicted | True Positives | Precision | Recall |
|---|---|---|---|---|---|
{q_table}
"""

    report = f"""# Second Opinion — Comprehensive Offline Evaluation Report

Generated: {now_str}  
Dataset Version: `{dataset_version}` ({len(EVALUATION_DATASET)} claim fixtures, {len(QUOTATION_EVALUATION_DATASET)} quotation fixtures)  
Evaluation Mode: 100% Offline (Deterministic BM25, Exact Substring/Subsequence Alignment, & Mocked Engine)

---

## 1. Executive Summary

| Evaluation Dimension | Metric | Measured Result | Target / Baseline |
|---|---|---|---|
| **Retrieval Quality** | Recall@1 | **{retrieval_summary['recall_at_1']:.4f}** | Baseline |
| **Retrieval Quality** | Recall@3 | **{retrieval_summary['recall_at_3']:.4f}** | Baseline |
| **Retrieval Quality** | Recall@5 | **{retrieval_summary['recall_at_5']:.4f}** | Baseline |
| **Retrieval Quality** | Mean Reciprocal Rank (MRR) | **{retrieval_summary['mrr']:.4f}** | Baseline |
| **Retrieval Quality** | Negative Detection Rate | **{retrieval_summary['negative_detection_rate']:.4f}** | 1.0000 |
| **Verdict Accuracy** | Overall Verdict Accuracy | **{verdict_summary['overall_accuracy']:.4f}** ({verdict_summary['correct_verdicts']}/{verdict_summary['total_fixtures']}) | 1.0000 |
| **Abstention Honesty** | Correct Abstention Rate | **{verdict_summary['correct_abstention_rate']:.4f}** | 1.0000 |
| **Security & Validation** | Fabricated Evidence ID Rejection | **{verdict_summary['adversarial_tests']['fabricated_id_rejection_rate']:.4f}** | 1.0000 (100%) |
| **Security & Validation** | Malformed Output Rejection | **{verdict_summary['adversarial_tests']['malformed_output_rejection_rate']:.4f}** | 1.0000 (100%) |
| **Operational Safety** | Operational Failure Leakage | **{verdict_summary['adversarial_tests']['operational_failure_leakage_to_factual_verdict']}** | 0 |
| **Quotation Auditing** | Overall Quote Accuracy | **{quotation_summary['overall_accuracy']:.4f}** ({quotation_summary['correct_matches']}/{quotation_summary['total_fixtures']}) | 1.0000 |

---

## 2. BM25 Retrieval Evaluation

### Aggregate Retrieval Performance
- **Positive Fixtures (Target Evidence Exists):** {retrieval_summary['positive_fixtures']}
- **Negative Fixtures (Pure Abstention Required):** {retrieval_summary['negative_fixtures']}
- **Recall@1:** {retrieval_summary['recall_at_1']:.4f}
- **Recall@3:** {retrieval_summary['recall_at_3']:.4f}
- **Recall@5:** {retrieval_summary['recall_at_5']:.4f}
- **MRR (Mean Reciprocal Rank):** {retrieval_summary['mrr']:.4f}
- **Negative Detection Rate:** {retrieval_summary['negative_detection_rate']:.4f}

### Retrieval Breakdown by Category
| Category | Total Fixtures | Positive Fixtures | Recall@1 | Recall@3 | MRR |
|---|---|---|---|---|---|
{cat_table}

---

## 3. Verdict Quality & Verification Evaluation

### Complete 4x4 Verdict Confusion Matrix
*(Rows: Ground Truth Expected Verdict; Columns: Predicted Persisted Verdict)*

| Expected \\ Predicted | `supported` | `contradicted` | `insufficiently_supported` | `ambiguous` |
|---|---|---|---|---|
{cm_table}

### Precision and Recall per Verdict
| Verdict Class | Expected (Support) | Predicted | True Positives | Precision | Recall |
|---|---|---|---|---|---|
{pvm_table}

### Adversarial Robustness and Operational Safety
- **Fabricated Evidence ID Rejection Rate:** {verdict_summary['adversarial_tests']['fabricated_id_rejection_rate'] * 100:.1f}% (Model cannot hallucinate citations outside candidate pool)
- **Malformed Response Rejection Rate:** {verdict_summary['adversarial_tests']['malformed_output_rejection_rate'] * 100:.1f}% (Schema non-compliance safely rejected)
- **Inconsistent Verdict Rejection Rate:** {verdict_summary['adversarial_tests']['inconsistent_verdict_rejection_rate'] * 100:.1f}% (Contradictory output logic rejected)
- **Operational Failures Converted to Factual Verdicts:** {verdict_summary['adversarial_tests']['operational_failure_leakage_to_factual_verdict']} (Strict non-leakage invariant maintained)

---

## 4. Retrieval Strategy Comparison

| Strategy | Chunk Size / Overlap | Top-K | Recall@1 | Recall@3 | Recall@5 | MRR | Negative Detection |
|---|---|---|---|---|---|---|---|
{strat_table}

### Comparative Findings & Recommendation
{experiments_summary['recommendation']}
{quote_section}

---

## 6. Known Evaluation Limitations & Blind Spots

1. **Synthetic vs. In-the-Wild Vocabulary Distribution:** The evaluation dataset uses controlled synthetic documents with clear factual anchors. Real-world documents may exhibit greater domain jargon, noisy OCR, or heavily obfuscated sentence structures.
2. **Lexical Paraphrase Ceiling:** Pure lexical retrieval (BM25) cannot bridge semantic gaps when zero keywords overlap between the claim and the source text without semantic embeddings or query expansion.
3. **Mocked Semantic Judgment vs. Production LLM Drift:** This offline framework rigorously tests the validation, persistence, schema parsing, and retrieval layers, but does not measure live LLM drift or real-world prompt variance.
4. **Quotation Formatting Artifacts:** Real-world PDFs may break words with unpredictable line wraps or unusual ligatures. The benchmark tests common dash, quote, and whitespace variants but does not encompass all desktop publishing quirks.
"""
    return report


def run_full_evaluation() -> dict:
    """Execute evaluation pipeline and persist results."""
    print("=" * 70)
    print("SECOND OPINION — COMPREHENSIVE EVALUATION RUNNER")
    print(f"Dataset Version: {DATASET_VERSION} | Total Fixtures: {len(EVALUATION_DATASET)}")
    print(f"Quotation Dataset Version: {QUOTATION_DATASET_VERSION} | Total Quotations: {len(QUOTATION_EVALUATION_DATASET)}")
    print("=" * 70)

    # 1. Retrieval Evaluation
    print("\n[1/4] Running BM25 Retrieval Evaluation...")
    retrieval_res = evaluate_retrieval(top_k=5)
    retrieval_dict = asdict(retrieval_res)
    print(f"  -> Recall@1: {retrieval_res.recall_at_1:.4f}")
    print(f"  -> Recall@3: {retrieval_res.recall_at_3:.4f}")
    print(f"  -> Recall@5: {retrieval_res.recall_at_5:.4f}")
    print(f"  -> MRR:      {retrieval_res.mrr:.4f}")
    print(f"  -> Negative Detection Rate: {retrieval_res.negative_detection_rate:.4f}")

    # 2. Verdict Evaluation
    print("\n[2/4] Running Claim Verdict Quality & Schema Validation...")
    verdict_res = evaluate_verdicts()
    verdict_dict = asdict(verdict_res)
    print(f"  -> Overall Verdict Accuracy: {verdict_res.overall_accuracy:.4f} ({verdict_res.correct_verdicts}/{verdict_res.total_fixtures})")
    print(f"  -> Correct Abstention Rate:  {verdict_res.correct_abstention_rate:.4f}")
    print(f"  -> Fabricated ID Rejection:  {verdict_res.adversarial_tests['fabricated_id_rejection_rate']:.4f}")

    # 3. Strategy Comparison
    print("\n[3/4] Running Comparative Retrieval Experiments...")
    experiments_dict = run_retrieval_experiments()
    print("  -> Comparative benchmark across 5 retrieval configurations complete.")

    # 4. Quotation Auditing Evaluation
    print("\n[4/4] Running Quotation Auditing Evaluation (Phase 7A)...")
    quotation_res = evaluate_quotations()
    quotation_dict = asdict(quotation_res)
    print(f"  -> Overall Quotation Accuracy: {quotation_res.overall_accuracy:.4f} ({quotation_res.correct_matches}/{quotation_res.total_fixtures})")

    # 5. Save Artifacts
    results_dir = Path(__file__).resolve().parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    json_path = results_dir / "evaluation_summary.json"
    full_summary = {
        "dataset_version": DATASET_VERSION,
        "quotation_dataset_version": QUOTATION_DATASET_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "retrieval_evaluation": retrieval_dict,
        "verdict_evaluation": verdict_dict,
        "retrieval_experiments": experiments_dict,
        "quotation_evaluation": quotation_dict,
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(full_summary, f, indent=2)

    md_report = generate_markdown_report(
        dataset_version=DATASET_VERSION,
        retrieval_summary=retrieval_dict,
        verdict_summary=verdict_dict,
        experiments_summary=experiments_dict,
        quotation_summary=quotation_dict,
    )
    md_path = results_dir / "evaluation_report.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_report)

    print(f"\nSaved machine-readable JSON to: {json_path}")
    print(f"Saved formatted Markdown report to: {md_path}")
    print("=" * 70)
    print("EVALUATION COMPLETED SUCCESSFULLY")
    print("=" * 70)

    return full_summary


if __name__ == "__main__":
    run_full_evaluation()
