"""SQLAlchemy ORM models defining the persistence layer for Second Opinion."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Text,
    Integer,
    Float,
    DateTime,
    ForeignKey,
)
from sqlalchemy.orm import relationship as orm_relationship

from database import Base


def generate_uuid() -> str:
    """Generate a stable string UUID."""
    return str(uuid.uuid4())


def utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)


class Run(Base):
    """A single verification run initiated by a user."""

    __tablename__ = "runs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    original_answer = Column(Text, nullable=False)
    status = Column(String(32), nullable=False, default="pending")  # pending, processing, completed, failed, timed_out
    current_stage = Column(String(64), nullable=False, default="initialized")
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)

    # Relationships
    sources = orm_relationship("Source", back_populates="run", cascade="all, delete-orphan")
    claims = orm_relationship("Claim", back_populates="run", cascade="all, delete-orphan")
    quote_audits = orm_relationship("QuoteAudit", back_populates="run", cascade="all, delete-orphan")


class Source(Base):
    """A user-supplied reference document or text."""

    __tablename__ = "sources"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    run_id = Column(String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    source_type = Column(String(32), nullable=False)  # text, pdf, url
    processing_status = Column(String(32), nullable=False, default="pending")  # pending, processing, success, partial, failed
    failure_reason = Column(Text, nullable=True)
    raw_content = Column(Text, nullable=True)
    content_length = Column(Integer, default=0, nullable=False)
    content_hash = Column(String(64), nullable=True)  # SHA-256 fingerprint
    page_count = Column(Integer, nullable=True)  # Total number of pages for PDF sources
    scanned_page_count = Column(Integer, default=0, nullable=False)  # Pages lacking extractable text
    extraction_metadata = Column(Text, nullable=True)  # JSON string of per-page extraction records
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Relationships
    run = orm_relationship("Run", back_populates="sources")
    chunks = orm_relationship("SourceChunk", back_populates="source", cascade="all, delete-orphan")
    evidence_items = orm_relationship("Evidence", back_populates="source", cascade="all, delete-orphan")


class SourceChunk(Base):
    """A discrete passage from a source preserved with location offsets."""

    __tablename__ = "source_chunks"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    source_id = Column(String(36), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    start_offset = Column(Integer, default=0, nullable=False)
    end_offset = Column(Integer, default=0, nullable=False)
    page_number = Column(Integer, nullable=True)  # 1-indexed for PDFs, null for text
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Relationships
    source = orm_relationship("Source", back_populates="chunks")
    evidence_items = orm_relationship("Evidence", back_populates="chunk")


class Claim(Base):
    """An atomic factual claim extracted from the original answer."""

    __tablename__ = "claims"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    run_id = Column(String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    original_text = Column(Text, nullable=False)
    normalized_text = Column(Text, nullable=False)
    position_in_answer = Column(Integer, nullable=True)
    verdict = Column(String(32), nullable=True)  # supported, contradicted, insufficiently_supported, ambiguous
    assessment_status = Column(String(32), nullable=False, default="pending")  # pending, assessed, failed
    reasoning = Column(Text, nullable=True)
    limitations = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Relationships
    run = orm_relationship("Run", back_populates="claims")
    evidence_items = orm_relationship("Evidence", back_populates="claim", cascade="all, delete-orphan")


class Evidence(Base):
    """A specific passage excerpt linking a claim to a source."""

    __tablename__ = "evidence"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    claim_id = Column(String(36), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True)
    source_id = Column(String(36), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_id = Column(String(36), ForeignKey("source_chunks.id", ondelete="SET NULL"), nullable=True)
    excerpt = Column(Text, nullable=False)
    source_location = Column(String(255), nullable=False)
    relationship = Column(String(32), nullable=False)  # supports, contradicts, partially_supports, irrelevant, conflicting, qualifies, tangential, candidate
    relevance_score = Column(Float, nullable=True)
    page_number = Column(Integer, nullable=True)  # 1-indexed PDF page number, None for text sources
    explanation = Column(Text, nullable=True)  # Human-readable explanation of how this evidence relates to the claim
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Relationships
    claim = orm_relationship("Claim", back_populates="evidence_items")
    source = orm_relationship("Source", back_populates="evidence_items")
    chunk = orm_relationship("SourceChunk", back_populates="evidence_items")


class QuoteAudit(Base):
    """Verification record of an explicit quotation in the AI answer against source text."""

    __tablename__ = "quote_audits"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    run_id = Column(String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    quotation_text = Column(Text, nullable=False)
    match_status = Column(String(32), nullable=False)  # exact_match, normalized_match, altered_quote, partial_match, unverifiable
    start_offset = Column(Integer, nullable=True)  # 0-based start character offset in original answer
    end_offset = Column(Integer, nullable=True)  # 0-based end character offset in original answer
    context = Column(Text, nullable=True)  # Surrounding sentence or attribution
    claim_id = Column(String(36), ForeignKey("claims.id", ondelete="SET NULL"), nullable=True)
    matched_source_id = Column(String(36), ForeignKey("sources.id", ondelete="SET NULL"), nullable=True)
    matched_source_title = Column(String(255), nullable=True)
    page_number = Column(Integer, nullable=True)  # 1-indexed for PDFs, null for text sources
    source_location = Column(String(255), nullable=True)
    source_start_offset = Column(Integer, nullable=True)
    source_end_offset = Column(Integer, nullable=True)
    source_excerpt = Column(Text, nullable=True)
    match_method = Column(String(32), nullable=True)  # exact, exact_cross_page, normalized, partial, model_assisted
    differences = Column(Text, nullable=True)
    audit_status = Column(String(32), nullable=False, default="completed")
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Relationships
    run = orm_relationship("Run", back_populates="quote_audits")
    matched_source = orm_relationship("Source", foreign_keys=[matched_source_id])
    claim = orm_relationship("Claim", foreign_keys=[claim_id])
