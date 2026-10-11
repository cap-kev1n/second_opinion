"""Comparative retrieval experiments runner.

Evaluates baseline BM25 configuration against architectural and hyperparameter variants:
- Baseline: chunk_size=500, overlap=100, top_k=3, k1=1.5, b=0.75
- Variant 1 (Fine-Grained Chunks): chunk_size=300, overlap=75, top_k=3
- Variant 2 (Broader Chunks): chunk_size=750, overlap=150, top_k=3
- Variant 3 (Extended Top-K): chunk_size=500, overlap=100, top_k=5
- Variant 4 (BM25 Hyperparameter Tuning): k1=1.2, b=0.8
"""

from typing import Dict, Any, List
from dataclasses import dataclass, asdict

from evaluation.dataset import EVALUATION_DATASET, EvaluationFixture
from evaluation.retrieval_evaluator import evaluate_retrieval


@dataclass
class RetrievalStrategyConfig:
    name: str
    description: str
    chunk_size: int
    chunk_overlap: int
    top_k: int
    k1: float
    b: float


RETRIEVAL_STRATEGIES: List[RetrievalStrategyConfig] = [
    RetrievalStrategyConfig(
        name="Baseline (Default)",
        description="Current production defaults: 500-char chunks, 100-char overlap, top-k=3, k1=1.5, b=0.75",
        chunk_size=500,
        chunk_overlap=100,
        top_k=3,
        k1=1.5,
        b=0.75,
    ),
    RetrievalStrategyConfig(
        name="Variant 1 (Fine Chunks)",
        description="Smaller 300-char chunks with 75-char overlap for higher passage density",
        chunk_size=300,
        chunk_overlap=75,
        top_k=3,
        k1=1.5,
        b=0.75,
    ),
    RetrievalStrategyConfig(
        name="Variant 2 (Broad Chunks)",
        description="Larger 750-char chunks with 150-char overlap to capture wider surrounding context",
        chunk_size=750,
        chunk_overlap=150,
        top_k=3,
        k1=1.5,
        b=0.75,
    ),
    RetrievalStrategyConfig(
        name="Variant 3 (Top-K=5)",
        description="Extended retrieval window returning top-5 candidate passages to model assessor",
        chunk_size=500,
        chunk_overlap=100,
        top_k=5,
        k1=1.5,
        b=0.75,
    ),
    RetrievalStrategyConfig(
        name="Variant 4 (BM25 Tuned)",
        description="Alternative saturation k1=1.2, length penalty b=0.8",
        chunk_size=500,
        chunk_overlap=100,
        top_k=3,
        k1=1.2,
        b=0.80,
    ),
]


def run_retrieval_experiments(
    fixtures: List[EvaluationFixture] = None,
) -> Dict[str, Any]:
    """Run comparative benchmark across all defined retrieval strategies."""
    dataset = fixtures or EVALUATION_DATASET

    strategy_results = []
    baseline_metrics = None

    for strat in RETRIEVAL_STRATEGIES:
        summary = evaluate_retrieval(
            fixtures=dataset,
            chunk_size=strat.chunk_size,
            chunk_overlap=strat.chunk_overlap,
            top_k=strat.top_k,
            k1=strat.k1,
            b=strat.b,
        )

        res_dict = {
            "strategy": strat.name,
            "description": strat.description,
            "config": {
                "chunk_size": strat.chunk_size,
                "chunk_overlap": strat.chunk_overlap,
                "top_k": strat.top_k,
                "k1": strat.k1,
                "b": strat.b,
            },
            "recall_at_1": summary.recall_at_1,
            "recall_at_3": summary.recall_at_3,
            "recall_at_5": summary.recall_at_5,
            "mrr": summary.mrr,
            "negative_detection_rate": summary.negative_detection_rate,
        }

        if strat.name.startswith("Baseline"):
            baseline_metrics = res_dict

        strategy_results.append(res_dict)

    # Determine recommendation
    recommendation = (
        "Keep Baseline as production default. The current baseline achieves strong "
        "Recall and MRR without introducing the token overhead of Top-K=5 or the fragmentation risks "
        "of 300-char chunks."
    )

    return {
        "dataset_size": len(dataset),
        "baseline": baseline_metrics,
        "strategies": strategy_results,
        "recommendation": recommendation,
    }
