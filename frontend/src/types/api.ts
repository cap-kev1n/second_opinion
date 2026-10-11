/**
 * API Contract types for Second Opinion frontend.
 * Matches backend Pydantic models in backend/models/schemas.py.
 */

export type Verdict =
  | 'supported'
  | 'contradicted'
  | 'insufficiently_supported'
  | 'ambiguous';

export type RunStatus =
  | 'pending'
  | 'processing'
  | 'completed'
  | 'failed'
  | 'timed_out';

export type AssessmentStatus =
  | 'pending'
  | 'assessed'
  | 'failed';

export type SourceProcessingStatus =
  | 'pending'
  | 'processing'
  | 'success'
  | 'partial'
  | 'failed';

export type EvidenceRelationship =
  | 'supports'
  | 'contradicts'
  | 'partially_supports'
  | 'irrelevant'
  | 'conflicting'
  | 'qualifies'
  | 'tangential'
  | 'candidate';

export type SourceType =
  | 'text'
  | 'pdf'
  | 'url';

export type QuoteMatchStatus =
  | 'exact_match'
  | 'normalized_match'
  | 'altered_quote'
  | 'partial_match'
  | 'unverifiable'
  | 'exact'
  | 'normalized_exact'
  | 'partial'
  | 'not_found'
  | 'not_checkable';

export interface SourceCreateRequest {
  title: string;
  source_type: SourceType;
  content?: string;
  url?: string;
}

export interface SourceResponse {
  id: string;
  run_id: string;
  title: string;
  source_type: SourceType;
  processing_status: SourceProcessingStatus;
  failure_reason?: string | null;
  content_length: number;
  content_hash?: string | null;
  content?: string | null;
  page_count?: number | null;
  scanned_page_count?: number;
  extraction_metadata?: string | null;
}

export interface EvidenceResponse {
  id: string;
  claim_id: string;
  source_id: string;
  source_title: string;
  chunk_id?: string | null;
  excerpt: string;
  source_location: string;
  relationship: EvidenceRelationship;
  relevance_score?: number | null;
  explanation?: string | null;
  page_number?: number | null;
}

export interface ClaimResponse {
  id: string;
  run_id: string;
  original_text: string;
  normalized_text: string;
  position_in_answer?: number | null;
  verdict?: Verdict | null;
  assessment_status: AssessmentStatus;
  reasoning?: string | null;
  limitations?: string | null;
  evidence: EvidenceResponse[];
}

export interface QuoteAuditResponse {
  id: string;
  run_id: string;
  quotation_text: string;
  match_status: QuoteMatchStatus;
  start_offset?: number | null;
  end_offset?: number | null;
  context?: string | null;
  claim_id?: string | null;
  matched_source_id?: string | null;
  matched_source_title?: string | null;
  page_number?: number | null;
  source_location?: string | null;
  source_start_offset?: number | null;
  source_end_offset?: number | null;
  source_excerpt?: string | null;
  match_method?: string | null;
  differences?: string | null;
  audit_status?: string;
}

export interface RunCreateRequest {
  answer: string;
  sources: SourceCreateRequest[];
}

export interface RunStatusResponse {
  run_id: string;
  status: RunStatus;
  current_stage: string;
  created_at: string;
  completed_at?: string | null;
  error_message?: string | null;
}

export interface ProcessingSummary {
  total_claims: number;
  supported: number;
  contradicted: number;
  insufficiently_supported: number;
  ambiguous: number;
  assessment_failures: number;
  sources_processed: number;
  sources_failed: number;
  coverage_note?: string | null;
}

export interface VerificationReportResponse {
  run_id: string;
  status: RunStatus;
  original_answer: string;
  summary: ProcessingSummary;
  claims: ClaimResponse[];
  quote_audits: QuoteAuditResponse[];
  sources: SourceResponse[];
  scope_disclaimer: string;
  created_at: string;
  completed_at?: string | null;
}

export interface HealthResponse {
  status: string;
  app_name: string;
  version: string;
  environment: string;
  timestamp: string;
}

export interface ApiError {
  detail: string;
  error_code?: string;
}
