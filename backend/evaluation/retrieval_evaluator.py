"""Offline evaluation engine for BM25 retrieval quality.

Computes:
- Recall@1, Recall@3, Recall@5
- Mean Reciprocal Rank (MRR)
- Negative detection rate (correct abstention when no evidence exists)
- Category-level breakdown
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict

from evaluation.dataset import EvaluationFixture, EVALUATION_DATASET
from services.chunker import chunk_source_text
from services.retrieval import BM25Retriever


@dataclass
class RetrievalFixtureResult:
    """Detailed retrieval metrics for a single fixture."""
    fixture_id: str
    category: str
    is_negative: bool
    num_candidates_retrieved: int
    first_relevant_rank: Optional[int]
    hit_at_1: bool
    hit_at_3: bool
    hit_at_5: bool
    reciprocal_rank: float
    retrieved_excerpts: List[str]


@dataclass
class RetrievalEvaluationSummary:
    """Aggregated retrieval evaluation metrics."""
    total_fixtures: int
    positive_fixtures: int
    negative_fixtures: int
    recall_at_1: float
    recall_at_3: float
    recall_at_5: float
    mrr: float
    negative_detection_rate: float
    by_category: Dict[str, Dict[str, float]]
    fixture_results: List[Dict[str, Any]]


def evaluate_retrieval(
    fixtures: Optional[List[EvaluationFixture]] = None,
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
    top_k: int = 5,
    k1: Optional[float] = None,
    b: Optional[float] = None,
) -> RetrievalEvaluationSummary:
    """Run deterministic offline retrieval evaluation against a fixture dataset."""
    dataset = fixtures if fixtures is not None else EVALUATION_DATASET

    results: List[RetrievalFixtureResult] = []

    pos_count = 0
    neg_count = 0
    neg_detected = 0

    hits_1 = 0
    hits_3 = 0
    hits_5 = 0
    rr_sum = 0.0

    category_stats: Dict[str, Dict[str, Any]] = {}

    for fix in dataset:
        cat = fix.category
        if cat not in category_stats:
            category_stats[cat] = {
                "total": 0,
                "positive": 0,
                "hits_1": 0,
                "hits_3": 0,
                "hits_5": 0,
                "rr_sum": 0.0,
            }
        category_stats[cat]["total"] += 1

        # Chunk all sources for this fixture
        all_chunks: List[Dict[str, Any]] = []
        chunk_counter = 0

        for src in fix.sources:
            t_chunks = chunk_source_text(
                source_text=src.content,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
            for tc in t_chunks:
                all_chunks.append({
                    "chunk_id": f"{src.id}-chk-{tc.chunk_index}",
                    "source_id": src.id,
                    "source_title": src.title,
                    "content": tc.content,
                    "start_offset": tc.start_offset,
                    "end_offset": tc.end_offset,
                    "chunk_index": tc.chunk_index,
                })
                chunk_counter += 1

        # Retrieve top_k candidates using BM25
        retriever = BM25Retriever(all_chunks, k1=k1, b=b)
        candidates = retriever.retrieve(query_text=fix.claim_text, top_k=top_k)

        is_neg = len(fix.expected_evidence_substrings) == 0

        first_rank: Optional[int] = None
        excerpts = [c.excerpt for c in candidates]

        if is_neg:
            neg_count += 1
            # For a negative fixture, success means either 0 candidates or no passage falsely matches
            is_detected = len(candidates) == 0
            if is_detected:
                neg_detected += 1
            reciprocal_rank = 0.0
            hit_1 = False
            hit_3 = False
            hit_5 = False
        else:
            pos_count += 1
            category_stats[cat]["positive"] += 1

            for rank_idx, cand in enumerate(candidates, start=1):
                # Candidate is relevant if ANY expected substring appears in its excerpt
                cand_lower = cand.excerpt.lower()
                if any(sub.lower() in cand_lower for sub in fix.expected_evidence_substrings):
                    first_rank = rank_idx
                    break

            hit_1 = first_rank == 1 if first_rank else False
            hit_3 = first_rank is not None and first_rank <= 3
            hit_5 = first_rank is not None and first_rank <= 5
            reciprocal_rank = 1.0 / first_rank if first_rank else 0.0

            if hit_1:
                hits_1 += 1
                category_stats[cat]["hits_1"] += 1
            if hit_3:
                hits_3 += 1
                category_stats[cat]["hits_3"] += 1
            if hit_5:
                hits_5 += 1
                category_stats[cat]["hits_5"] += 1
            rr_sum += reciprocal_rank
            category_stats[cat]["rr_sum"] += reciprocal_rank

        results.append(
            RetrievalFixtureResult(
                fixture_id=fix.id,
                category=cat,
                is_negative=is_neg,
                num_candidates_retrieved=len(candidates),
                first_relevant_rank=first_rank,
                hit_at_1=hit_1,
                hit_at_3=hit_3,
                hit_at_5=hit_5,
                reciprocal_rank=round(reciprocal_rank, 4),
                retrieved_excerpts=excerpts,
            )
        )

    # Compute aggregate metrics
    recall_1 = round(hits_1 / pos_count, 4) if pos_count > 0 else 0.0
    recall_3 = round(hits_3 / pos_count, 4) if pos_count > 0 else 0.0
    recall_5 = round(hits_5 / pos_count, 4) if pos_count > 0 else 0.0
    mrr = round(rr_sum / pos_count, 4) if pos_count > 0 else 0.0
    neg_rate = round(neg_detected / neg_count, 4) if neg_count > 0 else 1.0

    # Format category breakdown
    by_category_summary: Dict[str, Dict[str, float]] = {}
    for cat, stats in category_stats.items():
        pos = stats["positive"]
        by_category_summary[cat] = {
            "total_fixtures": stats["total"],
            "positive_fixtures": pos,
            "recall_at_1": round(stats["hits_1"] / pos, 4) if pos > 0 else 0.0,
            "recall_at_3": round(stats["hits_3"] / pos, 4) if pos > 0 else 0.0,
            "recall_at_5": round(stats["hits_5"] / pos, 4) if pos > 0 else 0.0,
            "mrr": round(stats["rr_sum"] / pos, 4) if pos > 0 else 0.0,
        }

    return RetrievalEvaluationSummary(
        total_fixtures=len(dataset),
        positive_fixtures=pos_count,
        negative_fixtures=neg_count,
        recall_at_1=recall_1,
        recall_at_3=recall_3,
        recall_at_5=recall_5,
        mrr=mrr,
        negative_detection_rate=neg_rate,
        by_category=by_category_summary,
        fixture_results=[asdict(r) for r in results],
    )
