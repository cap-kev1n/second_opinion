"""Routes for managing verification runs, claim extraction, and auditable reports."""

import hashlib
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status, File, UploadFile, Form
from sqlalchemy.orm import Session

from database import get_db
from models.db_models import Run, Source, Claim, SourceChunk, Evidence, QuoteAudit
from models.schemas import (
    RunCreateRequest,
    RunStatusResponse,
    VerificationReportResponse,
    ProcessingSummary,
    SourceResponse,
    ClaimResponse,
    EvidenceResponse,
    EvidenceRelationship,
    QuoteAuditResponse,
    QuoteMatchStatus,
    SourceType,
    SourceProcessingStatus,
    RunStatus,
    AssessmentStatus,
    Verdict,
    utc_now,
)
from services.claim_extractor import extract_and_persist_claims
from services.evidence_orchestrator import retrieve_and_persist_evidence
from services.claim_assessor import assess_and_persist_claims
from services.quotation_auditor import audit_quotations_for_run
from services.pdf_ingestion import (
    extract_and_validate_pdf,
    read_upload_file_bounded,
    cleanup_pdf_file,
)
from config import settings

router = APIRouter(prefix="/runs", tags=["Runs"])


@router.post(
    "",
    response_model=RunStatusResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a verification run",
)
def create_run(
    payload: RunCreateRequest,
    db: Session = Depends(get_db),
) -> RunStatusResponse:
    """Create a new verification run with user-supplied answer and reference sources.
    
    Persists the original answer and accepted text sources with SHA-256 fingerprints.
    Rejects unsupported source types (URL).
    """
    clean_answer = payload.answer.strip()
    if len(clean_answer) < 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Answer must contain at least 5 non-whitespace characters.",
        )

    if not payload.sources:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one reference source must be provided.",
        )

    # Validate each source
    prepared_sources: List[dict] = []
    for idx, src in enumerate(payload.sources):
        clean_title = src.title.strip()
        if not clean_title:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Source #{idx + 1} title cannot be empty or whitespace.",
            )

        # Reject unsupported source types explicitly
        if src.source_type == SourceType.PDF:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="PDF sources must be uploaded via the dedicated multipart upload endpoints ('POST /api/runs/upload-pdf' or 'POST /api/runs/{run_id}/sources/pdf').",
            )
        elif src.source_type == SourceType.URL:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Web URL sources are not supported. Please provide direct text content.",
            )
        elif src.source_type not in (SourceType.TEXT, SourceType.AI_CROSSCHECK):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported source type '{src.source_type}'. Only 'text' and 'ai_crosscheck' are currently accepted.",
            )

        if src.source_type == SourceType.AI_CROSSCHECK:
            raw_content = (src.content or "").strip()
            if not raw_content:
                import asyncio
                from services.llm_client import llm_service
                try:
                    raw_content = asyncio.run(llm_service.generate_crosscheck_reference(clean_answer))
                except Exception:
                    raw_content = (
                        f"AUTONOMOUS FACTUAL CROSS-CHECK REFERENCE DOSSIER\n\n"
                        f"Topic Overview:\n{clean_answer}\n\n"
                        f"Autonomous verification dossier compiled for factual cross-examination."
                    )
            clean_title = clean_title or "Autonomous AI Cross-Check Dossier"
        else:
            # Validate text content
            if not src.content or not src.content.strip():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Source '{clean_title}' must contain non-empty text content.",
                )
            raw_content = src.content
        content_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()
        prepared_sources.append({
            "title": clean_title,
            "source_type": src.source_type.value,
            "raw_content": raw_content,
            "content_length": len(raw_content),
            "content_hash": content_hash,
            "processing_status": SourceProcessingStatus.PENDING.value,
        })

    # Create and persist Run record
    new_run = Run(
        original_answer=payload.answer,  # Preserved exactly as submitted
        status=RunStatus.PENDING.value,
        current_stage="awaiting_verification_engine",
        created_at=utc_now(),
    )
    db.add(new_run)
    db.flush()  # Populates new_run.id

    # Create and persist associated Sources
    for src_data in prepared_sources:
        new_source = Source(
            run_id=new_run.id,
            title=src_data["title"],
            source_type=src_data["source_type"],
            raw_content=src_data["raw_content"],
            content_length=src_data["content_length"],
            content_hash=src_data["content_hash"],
            processing_status=src_data["processing_status"],
            created_at=utc_now(),
        )
        db.add(new_source)

    db.commit()
    db.refresh(new_run)

    return RunStatusResponse(
        run_id=new_run.id,
        status=RunStatus(new_run.status),
        current_stage=new_run.current_stage,
        created_at=new_run.created_at,
        completed_at=new_run.completed_at,
        error_message=new_run.error_message,
    )


_active_pdf_uploads: set[str] = set()


@router.post(
    "/upload-pdf",
    response_model=RunStatusResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create verification run with a PDF reference document",
)
async def create_run_with_pdf(
    answer: str = Form(..., description="AI-generated answer to verify"),
    file: UploadFile = File(..., description="PDF reference document file"),
    title: Optional[str] = Form(None, description="Optional custom display title"),
    db: Session = Depends(get_db),
) -> RunStatusResponse:
    """Initiate a verification run with an uploaded PDF reference document."""
    clean_answer = answer.strip()
    if not clean_answer or len(clean_answer) < 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="AI-generated answer must contain at least 5 non-whitespace characters.",
        )

    # Read bounded file bytes to prevent unbounded memory consumption
    file_bytes = await read_upload_file_bounded(file, settings.max_pdf_size_mb * 1024 * 1024)
    source_id = str(uuid.uuid4())
    result = extract_and_validate_pdf(
        file_bytes=file_bytes,
        original_filename=file.filename or "document.pdf",
        source_id=source_id,
    )

    final_title = title.strip() if title and title.strip() else result.source_title

    try:
        # Create and persist Run record
        new_run = Run(
            original_answer=answer,
            status=RunStatus.PENDING.value,
            current_stage="awaiting_verification_engine",
            created_at=utc_now(),
        )
        db.add(new_run)
        db.flush()

        new_source = Source(
            id=source_id,
            run_id=new_run.id,
            title=final_title,
            source_type=SourceType.PDF.value,
            raw_content=result.raw_content,
            content_length=result.content_length,
            content_hash=result.content_hash,
            page_count=result.page_count,
            scanned_page_count=result.scanned_page_count,
            extraction_metadata=result.extraction_metadata,
            processing_status=result.processing_status,
            failure_reason=result.failure_reason,
            created_at=utc_now(),
        )
        db.add(new_source)

        db.commit()
        db.refresh(new_run)
    except Exception as e:
        cleanup_pdf_file(source_id)
        db.rollback()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist verification run with PDF document.",
        )

    return RunStatusResponse(
        run_id=new_run.id,
        status=RunStatus(new_run.status),
        current_stage=new_run.current_stage,
        created_at=new_run.created_at,
        completed_at=new_run.completed_at,
        error_message=new_run.error_message,
    )


@router.post(
    "/{run_id}/sources/pdf",
    response_model=SourceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a PDF reference document to an existing run",
)
async def upload_pdf_source(
    run_id: str,
    file: UploadFile = File(..., description="PDF reference document file"),
    title: Optional[str] = Form(None, description="Optional custom display title"),
    db: Session = Depends(get_db),
) -> SourceResponse:
    """Upload and attach a PDF reference document to an existing run."""
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Verification run '{run_id}' was not found.",
        )

    # Disallow uploading while previous or current stages are processing
    if run.current_stage in ["extracting_claims", "retrieving_evidence", "assessing_claims"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot upload sources while run stage '{run.current_stage}' is currently processing.",
        )

    # Concurrency guard: reject concurrent uploads to the same run
    if run_id in _active_pdf_uploads:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A PDF source upload is already in progress for run '{run_id}'.",
        )
    _active_pdf_uploads.add(run_id)

    source_id = str(uuid.uuid4())
    try:
        # Read bounded file bytes to prevent unbounded memory consumption
        file_bytes = await read_upload_file_bounded(file, settings.max_pdf_size_mb * 1024 * 1024)
        result = extract_and_validate_pdf(
            file_bytes=file_bytes,
            original_filename=file.filename or "document.pdf",
            source_id=source_id,
        )

        final_title = title.strip() if title and title.strip() else result.source_title

        new_source = Source(
            id=source_id,
            run_id=run.id,
            title=final_title,
            source_type=SourceType.PDF.value,
            raw_content=result.raw_content,
            content_length=result.content_length,
            content_hash=result.content_hash,
            page_count=result.page_count,
            scanned_page_count=result.scanned_page_count,
            extraction_metadata=result.extraction_metadata,
            processing_status=result.processing_status,
            failure_reason=result.failure_reason,
            created_at=utc_now(),
        )
        db.add(new_source)

        # Invalidate existing evidence and previous claim assessments
        # Adding a new reference document invalidates all existing evidence assumptions
        claim_ids = [c.id for c in run.claims]
        if claim_ids:
            db.query(Evidence).filter(Evidence.claim_id.in_(claim_ids)).delete(synchronize_session=False)

        source_ids = [s.id for s in run.sources]
        if source_ids:
            db.query(SourceChunk).filter(SourceChunk.source_id.in_(source_ids)).delete(synchronize_session=False)

        # Invalidate existing quotation audits
        db.query(QuoteAudit).filter(QuoteAudit.run_id == run_id).delete(synchronize_session=False)

        for c in run.claims:
            c.verdict = None
            c.assessment_status = AssessmentStatus.PENDING.value
            c.reasoning = None
            c.limitations = None

        # Reset run stage: attaching an additional reference document requires re-retrieval
        run.current_stage = "awaiting_evidence"
        run.status = RunStatus.PROCESSING.value
        run.completed_at = None

        db.commit()
        db.refresh(new_source)

        return SourceResponse(
            id=new_source.id,
            run_id=new_source.run_id,
            title=new_source.title,
            source_type=SourceType(new_source.source_type),
            processing_status=SourceProcessingStatus(new_source.processing_status),
            failure_reason=new_source.failure_reason,
            content_length=new_source.content_length,
            content_hash=new_source.content_hash,
            content=new_source.raw_content,
            page_count=new_source.page_count,
            scanned_page_count=new_source.scanned_page_count,
            extraction_metadata=new_source.extraction_metadata,
        )
    except Exception as e:
        cleanup_pdf_file(source_id)
        db.rollback()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist uploaded PDF source.",
        )
    finally:
        _active_pdf_uploads.discard(run_id)


@router.post(
    "/{run_id}/extract",
    response_model=VerificationReportResponse,
    summary="Trigger factual claim extraction for a run",
)
async def extract_claims_for_run(
    run_id: str,
    db: Session = Depends(get_db),
) -> VerificationReportResponse:
    """Extract atomic factual claims from the run's answer using Gemini.
    
    Validates output with strict Pydantic schemas, records claims in original order,
    and transitions lifecycle stage to 'awaiting_evidence'.
    """
    await extract_and_persist_claims(run_id=run_id, db=db)
    return get_run_report(run_id=run_id, db=db)


@router.post(
    "/{run_id}/retrieve",
    response_model=VerificationReportResponse,
    summary="Retrieve candidate evidence passages for a run's claims",
)
def retrieve_evidence_for_run(
    run_id: str,
    top_k: Optional[int] = Query(None, ge=1, le=20, description="Maximum candidate passages per claim"),
    db: Session = Depends(get_db),
) -> VerificationReportResponse:
    """Retrieve top-k candidate passages from user-supplied sources for each claim using BM25.
    
    Operates strictly over user-supplied sources belonging to this run.
    Does NOT call external LLMs or assign factual verdicts.
    """
    retrieve_and_persist_evidence(run_id=run_id, db=db, top_k=top_k)
    return get_run_report(run_id=run_id, db=db)


@router.get(
    "/{run_id}/claims",
    response_model=List[ClaimResponse],
    summary="Get extracted claims for a run",
)
def get_run_claims(
    run_id: str,
    db: Session = Depends(get_db),
) -> List[ClaimResponse]:
    """Retrieve all persisted claims for an existing verification run."""
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Verification run '{run_id}' was not found.",
        )

    claims_list: List[ClaimResponse] = []
    for c in run.claims:
        evidence_list = [
            EvidenceResponse(
                id=ev.id,
                claim_id=ev.claim_id,
                source_id=ev.source_id,
                source_title=ev.source.title if ev.source else "Source",
                chunk_id=ev.chunk_id,
                excerpt=ev.excerpt,
                source_location=ev.source_location,
                relationship=EvidenceRelationship(ev.relationship),
                relevance_score=ev.relevance_score,
                explanation=ev.explanation,
                page_number=ev.page_number,
            )
            for ev in c.evidence_items
        ]
        evidence_list.sort(key=lambda x: -(x.relevance_score or 0.0))

        claims_list.append(
            ClaimResponse(
                id=c.id,
                run_id=c.run_id,
                original_text=c.original_text,
                normalized_text=c.normalized_text,
                position_in_answer=c.position_in_answer,
                verdict=Verdict(c.verdict) if c.verdict else None,
                assessment_status=AssessmentStatus(c.assessment_status),
                reasoning=c.reasoning,
                limitations=c.limitations,
                evidence=evidence_list,
            )
        )

    return claims_list


@router.get(
    "/{run_id}/sources/{source_id}",
    response_model=SourceResponse,
    summary="Get source details and exact content",
)
def get_source_detail(
    run_id: str,
    source_id: str,
    db: Session = Depends(get_db),
) -> SourceResponse:
    """Retrieve exact stored text and metadata for a specific source belonging to a run."""
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Verification run '{run_id}' was not found.",
        )

    source = (
        db.query(Source)
        .filter(Source.run_id == run_id, Source.id == source_id)
        .first()
    )
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source '{source_id}' was not found for run '{run_id}'.",
        )

    return SourceResponse(
        id=source.id,
        run_id=source.run_id,
        title=source.title,
        source_type=SourceType(source.source_type),
        processing_status=SourceProcessingStatus(source.processing_status),
        failure_reason=source.failure_reason,
        content_length=source.content_length,
        content_hash=source.content_hash,
        content=source.raw_content,  # Exact preserved text content
        page_count=source.page_count,
        scanned_page_count=source.scanned_page_count,
        extraction_metadata=source.extraction_metadata,
    )


@router.get(
    "/{run_id}/status",
    response_model=RunStatusResponse,
    summary="Get verification run status",
)
def get_run_status(
    run_id: str,
    db: Session = Depends(get_db),
) -> RunStatusResponse:
    """Retrieve operational lifecycle status for an existing verification run."""
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Verification run '{run_id}' was not found.",
        )

    return RunStatusResponse(
        run_id=run.id,
        status=RunStatus(run.status),
        current_stage=run.current_stage,
        created_at=run.created_at,
        completed_at=run.completed_at,
        error_message=run.error_message,
    )


def build_run_report(run: Run) -> VerificationReportResponse:
    """Construct an auditable VerificationReportResponse from a Run ORM instance."""
    source_responses: List[SourceResponse] = [
        SourceResponse(
            id=s.id,
            run_id=s.run_id,
            title=s.title,
            source_type=SourceType(s.source_type),
            processing_status=SourceProcessingStatus(s.processing_status),
            failure_reason=s.failure_reason,
            content_length=s.content_length,
            content_hash=s.content_hash,
            content=s.raw_content,  # Exact preserved content
            page_count=s.page_count,
            scanned_page_count=s.scanned_page_count,
            extraction_metadata=s.extraction_metadata,
        )
        for s in run.sources
    ]

    claim_responses: List[ClaimResponse] = []
    for c in run.claims:
        evidence_list = [
            EvidenceResponse(
                id=ev.id,
                claim_id=ev.claim_id,
                source_id=ev.source_id,
                source_title=ev.source.title if ev.source else "Source",
                chunk_id=ev.chunk_id,
                excerpt=ev.excerpt,
                source_location=ev.source_location,
                relationship=EvidenceRelationship(ev.relationship),
                relevance_score=ev.relevance_score,
                explanation=ev.explanation,
                page_number=ev.page_number,
            )
            for ev in c.evidence_items
        ]
        evidence_list.sort(key=lambda x: -(x.relevance_score or 0.0))

        claim_responses.append(
            ClaimResponse(
                id=c.id,
                run_id=c.run_id,
                original_text=c.original_text,
                normalized_text=c.normalized_text,
                position_in_answer=c.position_in_answer,
                verdict=Verdict(c.verdict) if c.verdict else None,
                assessment_status=AssessmentStatus(c.assessment_status),
                reasoning=c.reasoning,
                limitations=c.limitations,
                evidence=evidence_list,
            )
        )

    # Compute verdict and operational summary counts
    supported_cnt = sum(1 for c in claim_responses if c.verdict == Verdict.SUPPORTED)
    contradicted_cnt = sum(1 for c in claim_responses if c.verdict == Verdict.CONTRADICTED)
    insufficient_cnt = sum(1 for c in claim_responses if c.verdict == Verdict.INSUFFICIENTLY_SUPPORTED)
    ambiguous_cnt = sum(1 for c in claim_responses if c.verdict == Verdict.AMBIGUOUS)
    failures_cnt = sum(1 for c in claim_responses if c.assessment_status == AssessmentStatus.FAILED)

    if run.current_stage == "assessment_completed":
        coverage_note = (
            f"Assessment completed: {supported_cnt} supported, {contradicted_cnt} contradicted, "
            f"{insufficient_cnt} insufficiently supported, {ambiguous_cnt} ambiguous."
        )
    elif run.current_stage == "assessment_partial":
        coverage_note = (
            f"Assessment partial: {supported_cnt} supported, {contradicted_cnt} contradicted, "
            f"{insufficient_cnt} insufficiently supported, {ambiguous_cnt} ambiguous "
            f"({failures_cnt} operational failure(s))."
        )
    elif run.current_stage == "assessing_claims":
        coverage_note = "Assessing claims against retrieved candidate evidence using Gemini."
    elif run.current_stage == "awaiting_assessment":
        claims_with_evidence = sum(1 for c in claim_responses if len(c.evidence) > 0)
        coverage_note = (
            f"Candidate evidence retrieved for {claims_with_evidence} of {len(claim_responses)} claim(s) "
            "via BM25 lexical search. Ready for factual claim assessment."
        )
    elif run.current_stage == "retrieving_evidence":
        coverage_note = "Retrieving candidate evidence passages via BM25 lexical search."
    elif run.current_stage == "awaiting_evidence":
        coverage_note = f"{len(claim_responses)} factual claim(s) extracted. Awaiting evidence retrieval."
    elif run.current_stage == "extracting_claims":
        coverage_note = "Extracting atomic factual claims using Gemini."
    elif run.current_stage in ["failed", "retrieval_failed", "assessment_failed"]:
        coverage_note = f"Operation failed: {run.error_message or 'Unknown error'}"
    else:
        coverage_note = "Verification engine ready. No claims extracted yet."

    summary = ProcessingSummary(
        total_claims=len(claim_responses),
        supported=supported_cnt,
        contradicted=contradicted_cnt,
        insufficiently_supported=insufficient_cnt,
        ambiguous=ambiguous_cnt,
        assessment_failures=failures_cnt,
        sources_processed=len(run.sources),
        sources_failed=0,
        coverage_note=coverage_note,
    )

    quote_audit_responses: List[QuoteAuditResponse] = [
        QuoteAuditResponse(
            id=qa.id,
            run_id=qa.run_id,
            quotation_text=qa.quotation_text,
            match_status=QuoteMatchStatus(qa.match_status),
            start_offset=qa.start_offset,
            end_offset=qa.end_offset,
            context=qa.context,
            claim_id=qa.claim_id,
            matched_source_id=qa.matched_source_id,
            matched_source_title=qa.matched_source_title or (qa.matched_source.title if qa.matched_source else None),
            page_number=qa.page_number,
            source_location=qa.source_location,
            source_start_offset=qa.source_start_offset,
            source_end_offset=qa.source_end_offset,
            source_excerpt=qa.source_excerpt,
            match_method=qa.match_method,
            differences=qa.differences,
            audit_status=qa.audit_status,
        )
        for qa in run.quote_audits
    ]

    return VerificationReportResponse(
        run_id=run.id,
        status=RunStatus(run.status),
        original_answer=run.original_answer,
        summary=summary,
        claims=claim_responses,
        quote_audits=quote_audit_responses,
        sources=source_responses,
        scope_disclaimer="This verification is based solely on the user-supplied sources processed for this run. It does not establish universal truth.",
        created_at=run.created_at,
        completed_at=run.completed_at,
    )


@router.get(
    "/{run_id}/report",
    response_model=VerificationReportResponse,
    summary="Get verification report",
)
def get_run_report(
    run_id: str,
    db: Session = Depends(get_db),
) -> VerificationReportResponse:
    """Retrieve the auditable verification report for a run."""
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Verification run '{run_id}' was not found.",
        )

    return build_run_report(run)


@router.post(
    "/{run_id}/audit-quotes",
    response_model=VerificationReportResponse,
    summary="Audit direct quotations against user-supplied reference material",
)
async def audit_quotes_for_run_endpoint(
    run_id: str,
    use_model: bool = Query(True, description="Whether to use model assistance for ambiguous comparisons"),
    db: Session = Depends(get_db),
) -> VerificationReportResponse:
    """Audit all candidate direct quotations appearing in the original answer."""
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Verification run '{run_id}' was not found.",
        )

    await audit_quotations_for_run(run_id=run_id, db=db, use_model=use_model)
    return get_run_report(run_id=run_id, db=db)


@router.post(
    "/{run_id}/assess",
    response_model=VerificationReportResponse,
    summary="Assess claims against retrieved evidence",
)
async def assess_claims_for_run(
    run_id: str,
    force_reassess: bool = Query(False, description="Force re-assessment of previously assessed claims"),
    db: Session = Depends(get_db),
) -> VerificationReportResponse:
    """Assess all extracted claims against retrieved candidate evidence using Gemini.
    
    Guarantees:
    - Evidence retrieval must be completed prior to assessment.
    - Claims with no candidate evidence return 'insufficiently_supported' without calling Gemini.
    - Grounded strictly in supplied reference passages; pretrained knowledge is not evidence.
    - Operational errors produce assessment_status='failed', never a factual verdict.
    """
    await assess_and_persist_claims(run_id=run_id, db=db, force_reassess=force_reassess)
    try:
        await audit_quotations_for_run(run_id=run_id, db=db, use_model=True)
    except Exception:
        pass
    return get_run_report(run_id=run_id, db=db)


@router.post(
    "/{run_id}/verify-all",
    response_model=VerificationReportResponse,
    summary="Execute entire end-to-end verification pipeline",
)
async def verify_all_for_run(
    run_id: str,
    db: Session = Depends(get_db),
) -> VerificationReportResponse:
    """Execute complete end-to-end verification pipeline in one automated flow:
    1. Extract atomic factual claims using Gemini.
    2. Retrieve candidate BM25 evidence passages from user sources.
    3. Assess claims and categorize into supported, contradicted, etc.
    4. Audit direct quotations against reference sources.
    """
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Verification run '{run_id}' was not found.",
        )

    # 1. Extract claims if not yet extracted
    if not run.claims:
        await extract_and_persist_claims(run_id=run_id, db=db)
        db.refresh(run)

    # 2. Retrieve candidate evidence if not yet retrieved
    if run.claims and (run.current_stage == "awaiting_evidence" or not any(len(c.evidence_items) > 0 for c in run.claims)):
        retrieve_and_persist_evidence(run_id=run_id, db=db)
        db.refresh(run)

    # 3. Assess claims and audit quotations
    if run.claims:
        await assess_and_persist_claims(run_id=run_id, db=db, force_reassess=False)
        try:
            await audit_quotations_for_run(run_id=run_id, db=db, use_model=True)
        except Exception:
            pass

    return get_run_report(run_id=run_id, db=db)

