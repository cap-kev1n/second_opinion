"""Pydantic schemas and enums defining the Second Opinion API contracts."""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict


def utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)


# ==============================================================================
# Domain Enums
# ==============================================================================

class Verdict(str, Enum):
    """The four official user-facing verification verdicts."""
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    INSUFFICIENTLY_SUPPORTED = "insufficiently_supported"
    AMBIGUOUS = "ambiguous"


class RunStatus(str, Enum):
    """Lifecycle status of a verification run."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class AssessmentStatus(str, Enum):
    """Operational status of a claim assessment (distinct from factual verdicts)."""
    PENDING = "pending"
    ASSESSED = "assessed"
    FAILED = "failed"


class SourceProcessingStatus(str, Enum):
    """Processing state for an individual reference source."""
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class EvidenceRelationship(str, Enum):
    """Nature of evidence passage relationship to a claim."""
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    PARTIALLY_SUPPORTS = "partially_supports"
    IRRELEVANT = "irrelevant"
    CONFLICTING = "conflicting"
    QUALIFIES = "qualifies"
    TANGENTIAL = "tangential"
    CANDIDATE = "candidate"  # Lexically retrieved passage before verification


class SourceType(str, Enum):
    """Supported and planned reference source types."""
    TEXT = "text"
    PDF = "pdf"
    URL = "url"  # Reserved for future implementation
    AI_CROSSCHECK = "ai_crosscheck"  # Autonomous AI factual cross-check without manual source upload


class QuoteMatchStatus(str, Enum):
    """Audit status of explicit quotation in AI answer."""
    EXACT_MATCH = "exact_match"
    NORMALIZED_MATCH = "normalized_match"
    ALTERED_QUOTE = "altered_quote"
    PARTIAL_MATCH = "partial_match"
    UNVERIFIABLE = "unverifiable"
    # Backward-compatible legacy aliases
    EXACT = "exact"
    NORMALIZED_EXACT = "normalized_exact"
    PARTIAL = "partial"
    NOT_FOUND = "not_found"
    NOT_CHECKABLE = "not_checkable"


# ==============================================================================
# Source Schemas
# ==============================================================================

class SourceCreateRequest(BaseModel):
    """Payload to create or submit a source with a run."""
    title: str = Field(..., min_length=1, max_length=255, description="Source title or filename")
    source_type: SourceType = Field(default=SourceType.TEXT, description="Type of source")
    content: Optional[str] = Field(None, description="Raw text content for text sources")
    url: Optional[str] = Field(None, description="Source URL (reserved for future URL source type)")

    model_config = ConfigDict(extra="forbid")


class SourceResponse(BaseModel):
    """Public representation of a processed source."""
    id: str
    run_id: str
    title: str
    source_type: SourceType
    processing_status: SourceProcessingStatus
    failure_reason: Optional[str] = None
    content_length: int = 0
    content_hash: Optional[str] = None
    content: Optional[str] = Field(None, description="Exact raw text content of the source when available")
    page_count: Optional[int] = Field(None, description="Total number of pages for PDF documents")
    scanned_page_count: int = Field(0, description="Count of pages with little or no extractable text requiring OCR")
    extraction_metadata: Optional[str] = Field(None, description="JSON breakdown of per-page extraction records")

    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# Evidence & Claim Schemas
# ==============================================================================

class EvidenceResponse(BaseModel):
    """Evidence excerpt extracted from a user-supplied source."""
    id: str
    claim_id: str
    source_id: str
    source_title: str
    chunk_id: Optional[str] = None
    excerpt: str = Field(..., description="Exact passage extracted from source")
    source_location: str = Field(..., description="Page number and/or character offsets")
    page_number: Optional[int] = Field(None, description="1-indexed PDF page number, None for text sources")
    relationship: EvidenceRelationship = Field(
        default=EvidenceRelationship.CANDIDATE,
        description="Relationship to claim. Defaults to candidate for lexically retrieved passages.",
    )
    relevance_score: Optional[float] = None
    explanation: Optional[str] = Field(
        default=None,
        description="Explanation of how this passage relates to the claim",
    )

    model_config = ConfigDict(from_attributes=True)


class ClaimResponse(BaseModel):
    """Single atomic factual claim extracted from the original answer."""
    id: str
    run_id: str
    original_text: str = Field(..., description="Exact substring from original AI answer")
    normalized_text: str = Field(..., description="Self-contained normalized statement")
    position_in_answer: Optional[int] = Field(None, description="Character offset in original answer")
    verdict: Optional[Verdict] = Field(
        None,
        description="Factual verdict. None if assessment has not run or failed.",
    )
    assessment_status: AssessmentStatus = Field(
        default=AssessmentStatus.PENDING,
        description="Operational assessment state. FAILED represents processing error, not falsity.",
    )
    reasoning: Optional[str] = Field(None, description="Concise reasoning linked to evidence")
    limitations: Optional[str] = Field(None, description="Caveats, omissions, or scope constraints")
    evidence: List[EvidenceResponse] = Field(
        default_factory=list,
        description="List of evidence excerpts. Empty list indicates no evidence found.",
    )

    model_config = ConfigDict(from_attributes=True)


class QuoteAuditResponse(BaseModel):
    """Result of auditing an explicit quotation against source text."""
    id: str
    run_id: str
    quotation_text: str
    match_status: QuoteMatchStatus
    start_offset: Optional[int] = Field(None, description="0-based start character offset in original answer")
    end_offset: Optional[int] = Field(None, description="0-based end character offset in original answer")
    context: Optional[str] = Field(None, description="Surrounding sentence/context in original answer")
    claim_id: Optional[str] = Field(None, description="Associated claim ID if identifiable")
    matched_source_id: Optional[str] = None
    matched_source_title: Optional[str] = None
    page_number: Optional[int] = Field(None, description="1-indexed PDF page number, None for text sources")
    source_location: Optional[str] = None
    source_start_offset: Optional[int] = Field(None, description="0-based character offset in page/source text")
    source_end_offset: Optional[int] = Field(None, description="0-based character offset in page/source text")
    source_excerpt: Optional[str] = Field(None, description="Exact matching/relevant excerpt from reference source")
    match_method: Optional[str] = Field(None, description="Matching approach: exact, exact_cross_page, normalized, partial, or model_assisted")
    differences: Optional[str] = Field(None, description="Documented differences or explanation of status")
    audit_status: str = Field(default="completed", description="Operational status: completed or failed")

    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# Run & Report Schemas
# ==============================================================================

class RunCreateRequest(BaseModel):
    """Payload to initiate a new verification run."""
    answer: str = Field(..., min_length=5, description="AI-generated answer to verify")
    sources: List[SourceCreateRequest] = Field(
        ...,
        min_length=1,
        description="List of reference sources to check against",
    )

    model_config = ConfigDict(extra="forbid")


class RunStatusResponse(BaseModel):
    """Current execution status of a verification run."""
    run_id: str
    status: RunStatus
    current_stage: str = Field(..., description="Current pipeline stage (e.g., parsing, extracting)")
    created_at: datetime
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ProcessingSummary(BaseModel):
    """Summary counts for claims and sources in a verification run."""
    total_claims: int = 0
    supported: int = 0
    contradicted: int = 0
    insufficiently_supported: int = 0
    ambiguous: int = 0
    assessment_failures: int = 0
    sources_processed: int = 0
    sources_failed: int = 0
    coverage_note: Optional[str] = None


class VerificationReportResponse(BaseModel):
    """Complete auditable verification report for a run."""
    run_id: str
    status: RunStatus
    original_answer: str
    summary: ProcessingSummary
    claims: List[ClaimResponse] = Field(default_factory=list)
    quote_audits: List[QuoteAuditResponse] = Field(default_factory=list)
    sources: List[SourceResponse] = Field(default_factory=list)
    scope_disclaimer: str = Field(
        default="This verification is based solely on the user-supplied sources processed for this run. It does not establish universal truth.",
    )
    created_at: datetime
    completed_at: Optional[datetime] = None


# ==============================================================================
# Operational & Health Schemas
# ==============================================================================

class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "healthy"
    app_name: str
    version: str
    environment: str
    timestamp: datetime = Field(default_factory=utc_now)


class ErrorResponse(BaseModel):
    """Standard structured API error response."""
    detail: str
    error_code: str
    timestamp: datetime = Field(default_factory=utc_now)
