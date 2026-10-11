"""Evidence retrieval orchestration service.

Coordinates source text passage chunking, BM25 indexing, and candidate passage
retrieval for extracted claims, managing the run lifecycle stages.
"""

import json
from typing import List, Dict, Any, Optional
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from models.db_models import Run, Source, SourceChunk, Claim, Evidence
from models.schemas import RunStatus, AssessmentStatus, EvidenceRelationship, utc_now
from services.chunker import chunk_source_text
from services.retrieval import BM25Retriever
from services.pdf_ingestion import get_pdf_page_texts
from config import settings


def retrieve_and_persist_evidence(
    run_id: str,
    db: Session,
    top_k: Optional[int] = None,
) -> Run:
    """Chunk run sources and retrieve top-k candidate passages for each claim.
    
    Guarantees:
    - Scoped strictly to sources belonging to the active run.
    - Deterministic passage ranking with BM25.
    - All claim verdicts remain NULL and assessment_status remains PENDING.
    - Cross-run isolation enforced.
    - Clean idempotency on repeated executions.
    """
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Verification run '{run_id}' was not found.",
        )

    # Concurrency check
    if run.current_stage == "retrieving_evidence":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Evidence retrieval is already in progress for this run.",
        )

    # Pre-condition: Extraction must be completed before retrieval
    if run.current_stage in ["pending", "awaiting_verification_engine", "extracting_claims"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Claim extraction must be completed before retrieving evidence.",
        )

    # Atomic DB-level transition
    rows_updated = (
        db.query(Run)
        .filter(
            Run.id == run_id,
            Run.current_stage != "retrieving_evidence",
        )
        .update(
            {
                Run.status: RunStatus.PROCESSING.value,
                Run.current_stage: "retrieving_evidence",
                Run.error_message: None,
            },
            synchronize_session="fetch",
        )
    )
    db.commit()

    if rows_updated == 0:
        db.refresh(run)
        if run.current_stage == "retrieving_evidence":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Evidence retrieval is already in progress for this run.",
            )

    try:
        # Step 0: Clean existing evidence and chunks for this run (safe idempotency in reverse dependency order)
        claim_ids = [c.id for c in run.claims]
        if claim_ids:
            db.query(Evidence).filter(Evidence.claim_id.in_(claim_ids)).delete(synchronize_session=False)

        source_ids = [s.id for s in run.sources]
        if source_ids:
            db.query(SourceChunk).filter(SourceChunk.source_id.in_(source_ids)).delete(synchronize_session=False)

        # Step 1: Chunk each source belonging exclusively to this run
        all_chunk_dicts: List[Dict[str, Any]] = []

        for source in run.sources:
            # Check if source is a PDF
            if source.source_type == "pdf":
                page_records = get_pdf_page_texts(source.id, source.raw_content or "")
                if page_records:
                    for page_num, page_text in page_records:
                        if not page_text.strip():
                            continue

                        text_chunks = chunk_source_text(page_text)
                        for tc in text_chunks:
                            db_chunk = SourceChunk(
                                source_id=source.id,
                                content=tc.content,
                                start_offset=tc.start_offset,
                                end_offset=tc.end_offset,
                                page_number=page_num,
                                created_at=utc_now(),
                            )
                            db.add(db_chunk)
                            db.flush()

                            all_chunk_dicts.append({
                                "chunk_id": db_chunk.id,
                                "source_id": source.id,
                                "source_title": source.title,
                                "content": db_chunk.content,
                                "start_offset": db_chunk.start_offset,
                                "end_offset": db_chunk.end_offset,
                                "page_number": page_num,
                                "chunk_index": tc.chunk_index,
                            })
                    continue

            # Standard chunking for plain-text sources or legacy PDF fallback
            raw_text = source.raw_content or ""
            text_chunks = chunk_source_text(raw_text)

            for tc in text_chunks:
                db_chunk = SourceChunk(
                    source_id=source.id,
                    content=tc.content,
                    start_offset=tc.start_offset,
                    end_offset=tc.end_offset,
                    page_number=None,
                    created_at=utc_now(),
                )
                db.add(db_chunk)
                db.flush()  # Obtain db_chunk.id

                all_chunk_dicts.append({
                    "chunk_id": db_chunk.id,
                    "source_id": source.id,
                    "source_title": source.title,
                    "content": db_chunk.content,
                    "start_offset": db_chunk.start_offset,
                    "end_offset": db_chunk.end_offset,
                    "page_number": None,
                    "chunk_index": tc.chunk_index,
                })

        # Step 2: Initialize BM25 index over the run's chunks
        retriever = BM25Retriever(all_chunk_dicts)
        k = top_k if top_k is not None else settings.retrieval_top_k

        # Step 3: For each claim, retrieve top-k candidate passages
        for claim in run.claims:
            query = claim.normalized_text or claim.original_text
            candidates = retriever.retrieve(query, top_k=k)

            for cand in candidates:
                loc_str = (
                    f"Page {cand.page_number}, char {cand.start_offset}-{cand.end_offset}"
                    if cand.page_number is not None
                    else f"char {cand.start_offset}-{cand.end_offset}"
                )
                evidence = Evidence(
                    claim_id=claim.id,
                    source_id=cand.source_id,
                    chunk_id=cand.chunk_id,
                    excerpt=cand.excerpt,
                    source_location=loc_str,
                    page_number=cand.page_number,
                    relationship=EvidenceRelationship.CANDIDATE.value,
                    relevance_score=cand.relevance_score,
                    created_at=utc_now(),
                )
                db.add(evidence)

            # Invariant: verdict remains None, assessment status remains PENDING
            claim.verdict = None
            claim.assessment_status = AssessmentStatus.PENDING.value
            claim.reasoning = None
            claim.limitations = None

        # Step 4: Transition lifecycle stage to awaiting_assessment
        run.status = RunStatus.PROCESSING.value
        run.current_stage = "awaiting_assessment"
        run.completed_at = None
        run.error_message = None
        db.commit()
        db.refresh(run)

        return run

    except Exception as e:
        db.rollback()
        err_msg = str(e)
        try:
            failed_run = db.query(Run).filter(Run.id == run_id).first()
            if failed_run:
                failed_run.status = RunStatus.FAILED.value
                failed_run.current_stage = "retrieval_failed"
                failed_run.error_message = f"Evidence retrieval failed: {err_msg}"
                db.commit()
        except Exception:
            pass

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Evidence retrieval failed: {err_msg}",
        )
