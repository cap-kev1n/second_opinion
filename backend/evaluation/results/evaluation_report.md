# Second Opinion — Comprehensive Offline Evaluation Report

Generated: 2026-10-10 23:20:20 UTC  
Dataset Version: `1.0.0` (20 claim fixtures, 12 quotation fixtures)  
Evaluation Mode: 100% Offline (Deterministic BM25, Exact Substring/Subsequence Alignment, & Mocked Engine)

---

## 1. Executive Summary

| Evaluation Dimension | Metric | Measured Result | Target / Baseline |
|---|---|---|---|
| **Retrieval Quality** | Recall@1 | **0.9444** | Baseline |
| **Retrieval Quality** | Recall@3 | **0.9444** | Baseline |
| **Retrieval Quality** | Recall@5 | **0.9444** | Baseline |
| **Retrieval Quality** | Mean Reciprocal Rank (MRR) | **0.9444** | Baseline |
| **Retrieval Quality** | Negative Detection Rate | **1.0000** | 1.0000 |
| **Verdict Accuracy** | Overall Verdict Accuracy | **0.9500** (19/20) | 1.0000 |
| **Abstention Honesty** | Correct Abstention Rate | **1.0000** | 1.0000 |
| **Security & Validation** | Fabricated Evidence ID Rejection | **1.0000** | 1.0000 (100%) |
| **Security & Validation** | Malformed Output Rejection | **1.0000** | 1.0000 (100%) |
| **Operational Safety** | Operational Failure Leakage | **0** | 0 |
| **Quotation Auditing** | Overall Quote Accuracy | **1.0000** (12/12) | 1.0000 |

---

## 2. BM25 Retrieval Evaluation

### Aggregate Retrieval Performance
- **Positive Fixtures (Target Evidence Exists):** 18
- **Negative Fixtures (Pure Abstention Required):** 2
- **Recall@1:** 0.9444
- **Recall@3:** 0.9444
- **Recall@5:** 0.9444
- **MRR (Mean Reciprocal Rank):** 0.9444
- **Negative Detection Rate:** 1.0000

### Retrieval Breakdown by Category
| Category | Total Fixtures | Positive Fixtures | Recall@1 | Recall@3 | MRR |
|---|---|---|---|---|---|
| `direct_support` | 2 | 2 | 1.0000 | 1.0000 | 1.0000 |
| `direct_contradiction` | 2 | 2 | 0.5000 | 0.5000 | 0.5000 |
| `partial_support` | 1 | 1 | 1.0000 | 1.0000 | 1.0000 |
| `irrelevant_evidence` | 1 | 0 | 0.0000 | 0.0000 | 0.0000 |
| `conflicting_sources` | 1 | 1 | 1.0000 | 1.0000 | 1.0000 |
| `paraphrased_evidence_low_lexical_overlap` | 2 | 2 | 1.0000 | 1.0000 | 1.0000 |
| `numeric_claims_and_units` | 1 | 1 | 1.0000 | 1.0000 | 1.0000 |
| `dates_populations_conditions` | 2 | 2 | 1.0000 | 1.0000 | 1.0000 |
| `missing_qualifiers_overgeneralization` | 1 | 1 | 1.0000 | 1.0000 | 1.0000 |
| `compound_claims` | 1 | 1 | 1.0000 | 1.0000 | 1.0000 |
| `evidence_split_across_boundary` | 1 | 1 | 1.0000 | 1.0000 | 1.0000 |
| `no_relevant_evidence` | 1 | 0 | 0.0000 | 0.0000 | 0.0000 |
| `mixed_passages` | 2 | 2 | 1.0000 | 1.0000 | 1.0000 |
| `multiple_sources` | 1 | 1 | 1.0000 | 1.0000 | 1.0000 |
| `reconciled_conditions_not_conflicting` | 1 | 1 | 1.0000 | 1.0000 | 1.0000 |

---

## 3. Verdict Quality & Verification Evaluation

### Complete 4x4 Verdict Confusion Matrix
*(Rows: Ground Truth Expected Verdict; Columns: Predicted Persisted Verdict)*

| Expected \ Predicted | `supported` | `contradicted` | `insufficiently_supported` | `ambiguous` |
|---|---|---|---|---|
| **supported** | 9 | 0 | 0 | 0 |
| **contradicted** | 0 | 2 | 1 | 0 |
| **insufficiently_supported** | 0 | 0 | 7 | 0 |
| **ambiguous** | 0 | 0 | 0 | 1 |

### Precision and Recall per Verdict
| Verdict Class | Expected (Support) | Predicted | True Positives | Precision | Recall |
|---|---|---|---|---|---|
| `supported` | 9 | 9 | 9 | 1.0000 | 1.0000 |
| `contradicted` | 3 | 2 | 2 | 1.0000 | 0.6667 |
| `insufficiently_supported` | 7 | 8 | 7 | 0.8750 | 1.0000 |
| `ambiguous` | 1 | 1 | 1 | 1.0000 | 1.0000 |

### Adversarial Robustness and Operational Safety
- **Fabricated Evidence ID Rejection Rate:** 100.0% (Model cannot hallucinate citations outside candidate pool)
- **Malformed Response Rejection Rate:** 100.0% (Schema non-compliance safely rejected)
- **Inconsistent Verdict Rejection Rate:** 100.0% (Contradictory output logic rejected)
- **Operational Failures Converted to Factual Verdicts:** 0 (Strict non-leakage invariant maintained)

---

## 4. Retrieval Strategy Comparison

| Strategy | Chunk Size / Overlap | Top-K | Recall@1 | Recall@3 | Recall@5 | MRR | Negative Detection |
|---|---|---|---|---|---|---|---|
| **Baseline (Default)** | 500 / 100 | 3 | 0.9444 | 0.9444 | 0.9444 | 0.9444 | 1.0000 |
| **Variant 1 (Fine Chunks)** | 300 / 75 | 3 | 0.9444 | 0.9444 | 0.9444 | 0.9444 | 1.0000 |
| **Variant 2 (Broad Chunks)** | 750 / 150 | 3 | 0.9444 | 0.9444 | 0.9444 | 0.9444 | 1.0000 |
| **Variant 3 (Top-K=5)** | 500 / 100 | 5 | 0.9444 | 0.9444 | 0.9444 | 0.9444 | 1.0000 |
| **Variant 4 (BM25 Tuned)** | 500 / 100 | 3 | 0.9444 | 0.9444 | 0.9444 | 0.9444 | 1.0000 |

### Comparative Findings & Recommendation
Keep Baseline as production default. The current baseline achieves strong Recall and MRR without introducing the token overhead of Top-K=5 or the fragmentation risks of 300-char chunks.

---

## 5. Quotation Auditing Quality Evaluation (Phase 7A)

- **Dataset Version:** `1.0.0` (12 fixtures)
- **Overall Quotation Accuracy:** **100.0%** (12/12)

### Per-Outcome Breakdown
| Outcome Class | Expected | Predicted | True Positives | Precision | Recall |
|---|---|---|---|---|---|
| `exact_match` | 4 | 4 | 4 | 1.0000 | 1.0000 |
| `normalized_match` | 2 | 2 | 2 | 1.0000 | 1.0000 |
| `altered_quote` | 3 | 3 | 3 | 1.0000 | 1.0000 |
| `partial_match` | 1 | 1 | 1 | 1.0000 | 1.0000 |
| `unverifiable` | 2 | 2 | 2 | 1.0000 | 1.0000 |


---

## 6. Known Evaluation Limitations & Blind Spots

1. **Synthetic vs. In-the-Wild Vocabulary Distribution:** The evaluation dataset uses controlled synthetic documents with clear factual anchors. Real-world documents may exhibit greater domain jargon, noisy OCR, or heavily obfuscated sentence structures.
2. **Lexical Paraphrase Ceiling:** Pure lexical retrieval (BM25) cannot bridge semantic gaps when zero keywords overlap between the claim and the source text without semantic embeddings or query expansion.
3. **Mocked Semantic Judgment vs. Production LLM Drift:** This offline framework rigorously tests the validation, persistence, schema parsing, and retrieval layers, but does not measure live LLM drift or real-world prompt variance.
4. **Quotation Formatting Artifacts:** Real-world PDFs may break words with unpredictable line wraps or unusual ligatures. The benchmark tests common dash, quote, and whitespace variants but does not encompass all desktop publishing quirks.
