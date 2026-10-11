<<<<<<< HEAD
# Second Opinion

> **AI Answer Verification Platform**  
> Audits factual claims in AI-generated answers against explicitly supplied reference sources with verifiable, traceable evidence.

---

## 1. Project Overview

**Second Opinion** verifies factual claims in AI-generated text against reference sources chosen and provided by the user.

- **Source-Scoped Verification:** Claims are evaluated *exclusively* against the user's provided sources. The system does *not* perform silent web searches, consult unrequested external databases, or substitute general model knowledge for actual evidence.
- **Traceable Excerpts:** Every verdict links directly to exact passages with character offsets and page references.
- **Auditable Verdicts:** Distinguishes four user-facing verdicts:
  - `supported`: Selected sources provide relevant evidence corroborating the statement.
  - `contradicted`: Selected sources provide relevant evidence conflicting with the statement.
  - `insufficiently_supported`: Selected sources lack sufficient evidence to establish the statement. *(Missing evidence is never automatically assumed to mean false).*
  - `ambiguous`: The wording or evidence supports multiple materially distinct interpretations.
- **Quotation Audits:** Detects altered, partial, or authentic quotes against source documents.
- **Operational Failures Disclosed:** Source parsing failures or assessment timeouts are reported as operational statuses, never as factual verdicts.

---

## 2. Non-Negotiable Architectural Rules

1. **Integrated LLM API (Google Gemini):**
   - We do **NOT** build, train, fine-tune, or host our own LLM.
   - All future model operations use the official Google Gemini API via Google's maintained Python SDK (`google-genai`).
   - The LLM service is wrapped behind an abstract backend interface (`backend/services/llm_client.py`), ensuring provider changes do not require application rewrites.
2. **Server-Side Secret Management:**
   - The `GEMINI_API_KEY` is loaded exclusively on the backend via environment variables and is never exposed to browser code.
3. **No Phase 0 LLM Calls:**
   - In Phase 0, no calls to the Gemini API are executed. Application startup, schema validation, and test suites are 100% self-contained and run without external credentials.
4. **Source Integrity:**
   - User sources are treated as untrusted data. Model reasoning cannot invent evidence outside user documents.

---

## 3. Architecture & Directory Structure

```
d:\bitnbuild\
├── .env.example                         # Environment configuration template
├── .gitignore                           # Excludes secrets, venvs, DBs, node_modules
├── README.md                            # Complete setup and architecture documentation
│
├── backend/
│   ├── main.py                          # FastAPI application, CORS, lifespan, exception handlers
│   ├── config.py                        # Pydantic Settings loaded from .env
│   ├── database.py                      # SQLAlchemy engine, session generator, init_db
│   ├── requirements.txt                 # Pinned dependencies (FastAPI, SQLAlchemy, google-genai, etc.)
│   ├── data/                            # Local SQLite storage directory (.gitignore'd)
│   ├── models/
│   │   ├── __init__.py
│   │   ├── db_models.py                 # SQLAlchemy ORM models (Run, Source, Chunk, Claim, Evidence, QuoteAudit)
│   │   └── schemas.py                   # Pydantic request/response models & domain enums
│   ├── routes/
│   │   ├── __init__.py
│   │   └── health.py                    # Health check endpoint (GET /health, GET /api/health)
│   ├── services/
│   │   ├── __init__.py
│   │   └── llm_client.py                # Abstract LLM interface & GeminiLLMClient adapter
│   └── tests/
│       ├── __init__.py
│       ├── test_health.py               # Health endpoint tests
│       ├── test_schemas.py              # Pydantic enum & contract tests
│       ├── test_db.py                   # In-memory SQLite ORM and relationship tests
│       └── test_config.py               # Settings boundary tests
│
└── frontend/
    ├── package.json
    ├── tsconfig.json
    ├── vite.config.ts
    ├── index.html
    └── src/
        ├── main.tsx                     # Vite React entry point
        ├── App.tsx                      # React Router routes (/ and /report/:runId)
        ├── index.css                    # Responsive Vanilla CSS design system
        ├── types/
        │   └── api.ts                   # TypeScript interfaces matching backend contracts
        ├── api/
        │   └── client.ts                # Dedicated HTTP client with base URL configuration
        └── pages/
            ├── InputPage.tsx            # Verification input & backend health status
            └── ReportPage.tsx           # Placeholder report view
```

---

## 4. Technology Stack

| Layer | Technology | Details |
|---|---|---|
| **Frontend** | React 18, Vite, TypeScript | Modern, responsive SPA with React Router |
| **Backend** | Python 3.14 / 3.12, FastAPI | Asynchronous REST API, Pydantic v2 validation |
| **ORM / Storage** | SQLAlchemy 2.1, SQLite | File-based local database in `backend/data/` |
| **LLM Provider** | `google-genai` SDK | Official Gemini Python SDK (integrated in Phase 2+) |
| **PDF Extraction** | PyMuPDF (`fitz`) | Text extraction preserving page numbers (Phase 5) |
| **Testing** | pytest, httpx, TestClient | Automated test suite with in-memory DB isolation |

---

## 5. Prerequisites & Environment

- **Node.js:** v20+ (tested on Node v24.15.0 with npm 11.12.1)
- **Python:** v3.12+ (tested on Python 3.14.2 with pip 25.3)
- **Git Notice:** If `git` is not currently recognized on your Windows PATH, install [Git for Windows](https://gitforwindows.org/) or use your IDE's source control integration.

---

## 6. Setup and Startup Instructions (Windows)

### Step 1: Environment Configuration

Copy the `.env.example` file to `.env`:

```powershell
Copy-Item .env.example .env
```

Edit `.env` to configure your settings (a `GEMINI_API_KEY` is not required for Phase 0).

### Step 2: Backend Setup & Launch

Open a PowerShell terminal in the repository root:

```powershell
# Navigate to backend directory
cd backend

# Create virtual environment (if not already created)
python -m venv venv

# Activate virtual environment
.\venv\Scripts\Activate.ps1

# Install pinned dependencies
pip install -r requirements.txt

# Start the FastAPI development server
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

The backend server will be available at:
- **API Base:** `http://127.0.0.1:8000`
- **Health Check:** `http://127.0.0.1:8000/health`
- **Swagger Docs:** `http://127.0.0.1:8000/docs`

### Step 3: Frontend Setup & Launch

Open a separate PowerShell terminal in the repository root:

```powershell
# Navigate to frontend directory
cd frontend

# Install npm packages
npm install

# Start Vite development server
npm run dev
```

The frontend will be available at:
- **Web App:** `http://localhost:5173`

---

## 7. Running the Automated Test Suite

### Backend Tests

From the `backend/` directory with the virtual environment activated:

```powershell
# Run all unit and integration tests (isolated in-memory SQLite, deterministic BM25 and mocked LLM)
pytest -v
```

All 115 tests run against an isolated in-memory SQLite database and mocked LLM client without making external API calls or requiring a paid API key.

### Offline Evaluation Framework (Phase 5)

From the `backend/` directory:

```powershell
# Run the complete retrieval quality and claim verification evaluation suite
python -m evaluation.runner
```

Produces machine-readable metrics at `backend/evaluation/results/evaluation_summary.json` and a publication-ready Markdown report at `backend/evaluation/results/evaluation_report.md`.

### Frontend Type Check & Build

From the `frontend/` directory:

```powershell
# Check TypeScript types and build production bundle
npm run build
```

---

## 8. API Contract & Shared Types

### Domain Enums

- **Verdicts:** `supported`, `contradicted`, `insufficiently_supported`, `ambiguous`
- **Run Statuses:** `pending`, `processing`, `completed`, `failed`, `timed_out`
- **Assessment Statuses:** `pending`, `assessed`, `failed`
- **Source Processing Statuses:** `pending`, `processing`, `success`, `partial`, `failed`
- **Evidence Relationships:** `supports`, `contradicts`, `qualifies`, `tangential`, `candidate`
- **Source Types:** `text`, `pdf`, `url` *(url reserved for future)*

### Core Endpoints

| Method | Path | Status | Purpose |
|---|---|---|---|
| `GET` | `/health` / `/api/health` | **Implemented** | Health status check |
| `POST` | `/api/runs` | **Implemented** | Create new verification run & persist text sources |
| `GET` | `/api/runs/{id}/status` | **Implemented** | Poll execution progress / lifecycle stage |
| `GET` | `/api/runs/{id}/report` | **Implemented** | Retrieve auditable report with registered sources, claims & candidate evidence |
| `GET` | `/api/runs/{id}/sources/{source_id}` | **Implemented** | Retrieve exact unnormalized content for a verified source |
| `POST` | `/api/runs/{id}/extract` | **Implemented** | Trigger AI factual claim extraction via Google Gemini |
| `GET` | `/api/runs/{id}/claims` | **Implemented** | Retrieve persisted atomic claims for a run |
| `POST` | `/api/runs/{id}/retrieve` | **Implemented** | Retrieve candidate passages from user sources via BM25 |
| `POST` | `/api/runs/{id}/assess` | **Implemented** | Assess extracted claims against candidate passages via Gemini |
| `POST` | `/api/runs/{id}/sources` | Reserved (Phase 5) | Upload reference PDF |

### Run Lifecycle & Execution States

1. **`pending` (`awaiting_verification_engine`)**: Run created, answer and sources persisted. Extraction has not yet started.
2. **`processing` (`extracting_claims`)**: Claim extraction is actively running via Google Gemini. Concurrent extraction attempts return HTTP 409 Conflict.
3. **`processing` (`awaiting_evidence`)**: Atomic claims successfully extracted and persisted in original sequence order. Factual verdicts remain `None` and assessment status is `pending`. Ready for evidence retrieval.
4. **`processing` (`retrieving_evidence`)**: Source chunking and BM25 candidate retrieval are actively executing.
5. **`processing` (`awaiting_assessment`)**: Candidate passages retrieved and linked to claims. Verdicts remain `None` (NULL) and assessment status is `pending`. Ready for Phase 4 factual assessment.
6. **`processing` (`assessing_claims`)**: Evidence-grounded assessment is actively executing via Gemini with bounded concurrency.
7. **`completed` (`assessment_completed`)**: All claims evaluated and persisted with structured verdicts, human-readable reasoning, citations, and limitations.
8. **`processing` (`assessment_partial`)**: Some claims assessed successfully while one or more experienced operational errors; transparently disclosed in summary without fake verdicts.
9. **`failed` (`extraction_failed` / `retrieval_failed` / `assessment_failed`)**: Operational failure recorded cleanly without creating synthetic claims or fabricated evidence.

---

## 9. Current Phase Status

### Completed in Phase 0 & Phase 1 (Foundation & Run Lifecycle)
- [x] Initialized Vite React TypeScript frontend with client-side routing.
- [x] Initialized FastAPI backend with environment configuration and CORS.
- [x] Pinned backend dependencies in `requirements.txt`.
- [x] Defined complete SQLAlchemy ORM data models (`Run`, `Source`, `SourceChunk`, `Claim`, `Evidence`, `QuoteAudit`) with foreign keys and cascade rules.
- [x] Created matching Pydantic and TypeScript API schemas and domain enums.
- [x] Implemented `GET /health` without external API dependencies.
- [x] Created abstract `BaseLLMClient` and `GeminiLLMClient` adapter interface.
- [x] Implemented `POST /api/runs` validating inputs, preserving original answers, and computing SHA-256 fingerprints for accepted text sources.
- [x] Implemented `GET /api/runs/{run_id}/status` returning honest operational lifecycle states.
- [x] Implemented `GET /api/runs/{run_id}/report` returning persisted run and source records.
- [x] Connected React frontend `InputPage` to submit verification runs and navigate to `/report/:runId`.

### Completed in Phase 2 (Claim Extraction & Phase 1 Corrections)
- [x] **Phase 1 Correction (Source Inspection):** Implemented `GET /api/runs/{run_id}/sources/{source_id}` returning exact preserved `raw_content` scoped to the run. Added UI toggle on Report Page to inspect exact source text.
- [x] **Prompt Engineering (`backend/prompts/claim_extraction.py`):** Structured prompt instructing Gemini to extract atomic factual claims, split compound statements, preserve qualifications/numbers/units, ignore opinions/questions, and refrain from fact-checking or searching evidence.
- [x] **Strict Response Validation:** Enforced Pydantic schema validation (`ClaimExtractionResult`) on structured JSON returned by Gemini, rejecting malformed output without creating synthetic fallback claims.
- [x] **Gemini SDK Integration (`backend/services/llm_client.py`):** Configured official `google-genai` SDK with explicit timeouts, bounded retries (1 retry max), and structured response schema (`response_schema`).
- [x] **Extraction Orchestration (`backend/services/claim_extractor.py`):** Managed lifecycle transitions (`pending` -> `extracting_claims` -> `awaiting_evidence`), concurrency locks (HTTP 409), idempotency, and transactional DB persistence.
- [x] **Honest Verdict Invariants:** Stored claims strictly with `verdict = None` and `assessment_status = "pending"`.
- [x] **Extraction API Endpoints (`POST /api/runs/{id}/extract`, `GET /api/runs/{id}/claims`):** Safe POST trigger and GET claim retrieval. GET endpoints never invoke LLMs.
- [x] **Frontend Report Page Integration:** Added "Extract Factual Claims" action, live extraction spinner, explicit "Extracted — Not Yet Fact-Checked" badges, verbatim quote callouts, and empty claim state handling.

### Completed in Phase 3 (Source Passage Chunking & Evidence Retrieval)
- [x] **Deterministic Source Chunker (`backend/services/chunker.py`):** Implemented sentence/paragraph-aware chunking preserving exact substrings with half-open offsets `[start, end)`. Strict invariant `source_text[start:end] == chunk_text` verified for all chunks. Configurable chunk size and overlap.
- [x] **Okapi BM25 Retrieval Engine (`backend/services/retrieval.py`):** Implemented deterministic lexical retrieval with Robertson IDF and stopword filtering. Scoped strictly to sources belonging to the active run (zero cross-run leakage).
- [x] **Evidence Orchestration Service (`backend/services/evidence_orchestrator.py`):** Idempotently chunks sources into `SourceChunk` records and retrieves top-k candidate passages into `Evidence` records (`relationship="candidate"`). Manages concurrency with atomic database updates.
- [x] **Strict Non-Verdict Principle:** Invariant maintained: all claim verdicts remain `None` (NULL) and assessment statuses remain `pending`. Candidate evidence is never conflated with factual verification.
- [x] **Retrieval API Endpoint (`POST /api/runs/{id}/retrieve`):** Safe POST action with configurable `top_k` query parameter. Rejects retrieval if claims have not been extracted (HTTP 400). Read-only GET endpoints never invoke retrieval.
- [x] **Frontend Candidate Evidence UI (`frontend/src/pages/ReportPage.tsx`):** Added "Find Candidate Evidence (BM25)" action button, live spinner, candidate passage cards with source title, character offsets, raw BM25 relevance scores, and neutral unassessed badges. Displays neutral "No relevant passage retrieved" message when no lexical matches exist.

### Completed in Phase 4 (Evidence-Grounded Claim Assessment)
- [x] **Evidence-Grounded Prompting (`backend/prompts/claim_assessment.py`):** Dedicated prompt module requiring Gemini to ground verification strictly and exclusively in the user-supplied candidate excerpts. Explicitly forbids using pretrained knowledge as evidence. Treats source excerpts as untrusted text to prevent prompt injection.
- [x] **Structured Assessment Schema & Validation:** Strict Pydantic models (`ClaimAssessmentResult`, `EvidenceAssessmentItem`) requiring verdicts, reasoning, and per-evidence relationship classifications (`supports`, `contradicts`, `partially_supports`, `irrelevant`, `conflicting`) with non-empty explanations.
- [x] **Strict Model Output Post-Validation (`validate_model_assessment`):** Verifies all referenced evidence IDs belong strictly to the claim's candidate evidence pool (rejects fabricated or cross-run IDs), rejects duplicates, and enforces logical consistency between evidence relationships and overall verdicts.
- [x] **No-Evidence Rule:** When zero candidate passages were retrieved for a claim, Gemini is completely bypassed: immediately assigns `insufficiently_supported` with an explicit explanation that no relevant evidence was found. Never assumes missing evidence implies falsity.
- [x] **The Four Factual Verdicts:**
  - `supported`: The supplied evidence directly and sufficiently proves the material substance of the claim.
  - `contradicted`: The supplied evidence explicitly and directly conflicts with the material substance of the claim.
  - `insufficiently_supported`: The supplied evidence does not establish the claim and does not provide grounds to conclude it is false.
  - `ambiguous`: Supplied sources conflict and cannot be resolved, or wording admits materially conflicting interpretations.
- [x] **Assessment Orchestration Service (`backend/services/claim_assessor.py`):** Asynchronously evaluates claims with bounded concurrency (`asyncio.Semaphore(3)`). Enforces lifecycle transitions (`awaiting_assessment` -> `assessing_claims` -> `assessment_completed` / `assessment_partial`). Database transactions are never held open during external LLM calls.
- [x] **Operational Failure Isolation:** Provider timeouts or schema failures mark `claim.assessment_status = "failed"` with `claim.verdict = None`. Operational failures NEVER become factual verdicts.
- [x] **Assessment API Endpoint (`POST /api/runs/{id}/assess`):** Triggers assessment with optional `force_reassess` flag. Enforces preconditions (rejects assessment before retrieval with HTTP 400, concurrent requests with HTTP 409).
- [x] **Frontend Verdict Presentation (`frontend/src/pages/ReportPage.tsx`):** Added "Verify Claims Against Sources" action, real-time assessing indicators, four color-coded verdict badges, human-readable reasoning cards, limitations/caveats boxes, assessed evidence cards with relationship pills, and per-passage explanations.
- [x] **Deterministic Offline Test Suite (`backend/tests/test_claim_assessment.py`):** 25 targeted tests covering all 30 Phase 4 requirements using deterministic mocks (zero live API calls required). Total 88 passing backend tests.

### Completed in Phase 4.1 (Independent Verification & Reliability Audit)
- [x] **Strict Logical Consistency Invariants:** Enforced comprehensive invariants in `validate_model_assessment`:
  - `supported` requires at least one directly supporting passage and cannot contain contradictory or conflicting passages.
  - `contradicted` requires at least one directly contradicting passage and cannot contain supporting or conflicting passages.
  - Conflicting support and contradiction must be resolved as `ambiguous`.
  - Claims with all `irrelevant` evidence must be evaluated as `insufficiently_supported`.
  - `ambiguous` cannot be assigned when all evidence is irrelevant.
- [x] **Cross-Source Conflict & Immutability:** Regressed and verified that conflicting passages are never discarded, per-evidence relationships and explanations are accurately persisted, and source content, original answer text, claim text, and BM25 scores remain strictly immutable.
- [x] **Concurrency & Stuck-State Recovery:** Added active in-process execution tracking (`_active_assessments`). Concurrent executions for the same run return HTTP 409 Conflict. If a process crash or worker failure leaves a run in `assessing_claims`, calling `force_reassess=True` safely recovers the stuck run.
- [x] **Evidence Invalidation on Re-Retrieval:** Verified that re-running evidence retrieval (`retrieve_and_persist_evidence`) completely wipes prior verdicts, reasoning, limitations, and sets evidence back to candidate state. Failed reassessments cleanly reset evidence relationships to `candidate`.
- [x] **Stress & Large-Run Resilience:** Verified runs with 50 and 100 claims execute with bounded concurrency semaphores, handle partial operational failures, and support selective retries of failed claims without repeating completed assessments.
- [x] **Backward-Compatibility Database Migration:** Added automatic SQLite schema migration in `database.init_db()` that dynamically checks and adds missing columns (`evidence.explanation`, `claims.reasoning`, `claims.limitations`, etc.) ensuring older SQLite databases from Phase 1-3 load and operate without errors.
- [x] **Comprehensive Adversarial Regression Suite (`backend/tests/test_audit_phase41.py`):** 16 targeted adversarial and stress tests. Total 104 passing backend tests (100% offline, 0 warnings/errors).
- [x] **Evaluation Archetypes Fixture (`backend/tests/test_evaluation_fixtures.py`):** 6 archetype benchmarks covering supported, contradicted, topic match without establishment, silent source, conflicting sources, and partial compound claims.
- [x] **Frontend Production Build Verified:** `tsc -b && vite build` and `oxlint` pass with 0 errors and 0 warnings.

### Completed in Phase 5 (Retrieval Quality & Verification Evaluation Framework)
- [x] **Version-Controlled Synthetic Evaluation Dataset (`backend/evaluation/dataset.py`):** Curated 20 deterministic fixtures covering all 15 core evaluation categories: direct support, direct contradiction, partial compound support, irrelevant evidence, conflicting sources, low lexical overlap paraphrases, numeric and unit discrepancies, dates/populations/conditions meaning changes, missing qualifiers, boundary splits, negative fixtures, mixed distractors, multi-source attribution, and reconciled conditions.
- [x] **BM25 Retrieval Evaluator (`backend/evaluation/retrieval_evaluator.py`):** Deterministic offline evaluator calculating Recall@1 (0.9444), Recall@3 (0.9444), Recall@5 (0.9444), MRR (0.9444), and negative detection rate (1.0000). Handles empty result sets, partial relevance, and ties deterministically.
- [x] **Verdict Quality & Schema Evaluator (`backend/evaluation/verdict_evaluator.py`):** Evaluates real DB persistence, schema validation, and report serialization using mocked responses. Computes full 4x4 Confusion Matrix, per-verdict precision/recall, and correct abstention rate (1.0000). Confirms 100% rejection of fabricated IDs, malformed outputs, and zero leakage of operational failures into factual verdicts.
- [x] **Comparative Retrieval Experiments (`backend/evaluation/experiments.py`):** Compares baseline BM25 (chunk=500, overlap=100, top_k=3) against 4 alternative strategies (fine chunks, broad chunks, top-k=5, tuned saturation/length parameters). Documents trade-offs and confirms baseline stability.
- [x] **Evaluation CLI Runner (`backend/evaluation/runner.py`):** Single executable command (`python -m evaluation.runner`) generating machine-readable JSON (`evaluation_summary.json`) and formatted Markdown report (`evaluation_report.md`).
- [x] **Evaluation Framework Test Suite (`backend/tests/test_evaluation_framework.py`):** 11 regression tests verifying metric formulas, tie-breaking, confusion matrix conservation, dataset schema validity, and negative detection. Total 115 passing backend tests.

### Completed in Phase 6 (PDF Reference Document Ingestion & Page-Level Evidence Attribution)
- [x] **PyMuPDF Document Ingestion (`backend/services/pdf_ingestion.py`):** Ingests PDF reference documents using the official PyMuPDF library (`pymupdf`). Extracts text page-by-page preserving 1-based page numbers and character counts without concatenating or losing page divisions.
- [x] **Strict Security & Resource Enforcement:**
  - Enforces `max_pdf_size_mb` (10 MB, HTTP 413 Content Too Large).
  - Validates `%PDF-` magic header bytes to reject spoofed files (HTTP 400).
  - Enforces `max_pdf_pages` (100 pages, HTTP 400).
  - Detects and rejects encrypted or password-protected PDFs (HTTP 400).
  - Sanitizes client-provided filenames and saves raw PDFs under safe UUID paths (`data/pdf_uploads/{source_id}.pdf`).
- [x] **Scanned & Empty Page Detection:** Detects empty pages or pages with fewer than 10 characters / 3 words. Persists `scanned_page_count` on `Source` and surfaces clear warnings in extraction metadata that Optical Character Recognition (OCR) may be required. Rejects completely unreadable PDFs where zero text can be extracted across all pages (HTTP 400).
- [x] **Per-Page Chunking & Offset Provenance (`backend/services/evidence_orchestrator.py`):**
  - Chunks each page independently; chunks **never** span page boundaries.
  - Computes character offsets `[start, end)` relative to page text, preserving exact substring invariant: `page_text[start:end] == chunk.content`.
  - Persists `page_number` on `SourceChunk` and propagates to `Evidence` (`page_number`) and `CandidatePassage`.
  - Formats `Evidence.source_location` as `"Page {page_number}, char {start}-{end}"` for PDFs while preserving `"char {start}-{end}"` for text sources.
- [x] **Dedicated PDF Endpoints (`backend/routes/runs.py`):**
  - `POST /api/runs/upload-pdf`: Creates a verification run with an uploaded PDF reference document via multipart form data (`answer`, `file`, optional `title`).
  - `POST /api/runs/{run_id}/sources/pdf`: Attaches an additional PDF reference document to an existing run. Reverts stage to `awaiting_evidence` if run was previously assessed, prompting clean re-retrieval without stale evidence.
  - Concurrency safety: Rejects uploads while extraction, retrieval, or assessment is actively processing (HTTP 409 Conflict).
- [x] **Database Schema Migration (`backend/database.py`):** Automatically migrates SQLite schema in `init_db()` by checking for and adding `sources.page_count`, `sources.scanned_page_count`, `sources.extraction_metadata`, and `evidence.page_number`. Fully backwards-compatible with existing databases.
- [x] **Frontend PDF Upload & Provenance UI:**
  - `frontend/src/pages/InputPage.tsx`: Activated "PDF Document" tab with file picker, file size formatted display, validation (10MB limit, `.pdf` extension), and submission via `apiClient.createRunWithPdf`.
  - `frontend/src/pages/ReportPage.tsx`: Displays source type `PDF`, page count (`{src.page_count} pages`), scanned page OCR warnings (`⚠️ X scanned/empty page(s)`), "+ Attach PDF Document" button with inline upload form, and clear `Page {ev.page_number}` badges on evidence cards.
- [x] **Comprehensive Offline Test Suite (`backend/tests/test_pdf_ingestion.py`):** 13 deterministic tests using programmatic PyMuPDF generation (multi-page extraction, exact per-page chunking invariants, scanned page detection, magic bytes, size limit, page limit, encrypted rejection, corruption, API endpoints, 409 conflict, end-to-end provenance, and backward compatibility). Total 128 passing backend tests.

### Completed in Phase 7A (Quotation Auditing)
- [x] **Direct Quotation Extraction (`backend/services/quotation_auditor.py`):**
  - Extracts candidate direct quotations using documented 0-based Python Unicode code-point offsets `[start, end)`.
  - Supports straight double/single quotes, curly typographic quotes (`“”`, `‘’`), and French guillemets (`«»`).
  - Supports multiline quotes and preserves surrounding attribution context sentence.
  - Heuristically avoids false positives like ordinary contractions (`it's`, `don't`, `user's`) and short quoted words.
  - Preserves original answer integrity (never silently rewrites the answer text).
- [x] **Conservative Deterministic Matching & Provenance:**
  - `exact_match`: Verbatim substring found in supplied text sources or single/multi-page PDF extracts.
  - `normalized_match`: Matches under strictly conservative normalization: smart quote folding, dash normalization (`—`, `–` -> `-`), soft hyphen removal (`\xad`), and whitespace collapse.
  - **Normalization Safety Invariants:** Normalization *never* strips meaningful negations (`not`, `never`, `no`), never alters numbers or units, and never discards qualifiers (`often`, `primarily`).
  - `altered_quote`: Identifies substantive differences (word substitution, omitted key words, changed figures or negations) where candidate source text provides enough context for comparison.
  - `partial_match`: Only an authentic fragment/prefix/suffix is located, distinguishing truncated text from fabricated or altered text.
  - `unverifiable`: Available evidence lacks sufficient coverage to verify or refute quotation authenticity (missing source text is *never* automatically classified as fabricated).
- [x] **PDF & Multi-Page Provenance Invariants:**
  - Preserves 1-based page numbers and page-relative code-point offsets for PDF sources.
  - Detects and verifies quotations split across consecutive extracted PDF pages, recording multi-page provenance (`Pages X-Y`).
  - Resolves identical text across multiple pages deterministically (links to the first occurrence without inventing page numbers).
- [x] **Secure Model-Assisted Interpretation (`GeminiLLMClient.audit_quotation`):**
  - Used strictly when deterministic token alignment detects candidate passages requiring semantic classification (e.g., distinguishing extraction hyphenation from substantive word alteration).
  - Supplies *only* candidate source excerpts and quotation to Gemini.
  - Treats quotation and reference documents strictly as untrusted data within `<candidate_quotation>` and `<reference_evidence>` blocks, neutralizing prompt injection attacks.
  - Validates model output against actual supplied candidate source IDs; rejects fabricated IDs and model hallucinations.
  - Operational failures gracefully fall back to deterministic assessment without corrupting the outcome.
- [x] **Run Lifecycle & Invalidation Integration:**
  - Added `POST /api/runs/{run_id}/audit-quotes` endpoint and wired quotation auditing into `POST /api/runs/{run_id}/assess`.
  - Re-auditing atomically invalidates prior quote audit records for the run.
  - Attaching new PDF or text reference documents safely wipes existing quotation audits and verdicts to prevent stale verification results.
  - Maintains strict cross-run isolation.
- [x] **Frontend Quotation Presentation (`frontend/src/pages/ReportPage.tsx`):**
  - Added dedicated "Direct Quotation Audits" card section with outcome badges (`✓ Exact Match`, `≈ Normalized Match`, `≠ Altered Quote`, `◐ Partial Match`, `? Unverifiable`).
  - Shows original answer offsets, attribution context, associated claim links, source provenance (title, page, offsets), verbatim source excerpts, and discrepancy explanations.
  - Features an explicit "Audit Direct Quotations" action button.
- [x] **Quotation Evaluation Benchmark (`backend/evaluation/quotation_dataset.py`, `quotation_evaluator.py`):**
  - Created a versioned 12-fixture offline quotation dataset covering all outcomes: exact match, curly normalization, altered number, altered negation, partial truncation, absent source, PDF cross-page split, identical text multi-page, prompt injection, and extraction noise.
  - Integrated into evaluation runner (`python -m evaluation.runner`) achieving 100% accuracy (12/12) without network calls.
- [x] **Deterministic Offline Test Suite (`backend/tests/test_quotation_auditor.py`):**
  - 20 targeted tests covering straight/curly quotes, multiline quotes, normalization invariants, exact/normalized matches, altered numbers/negations, partial matches, cross-page PDF quotes, prompt injection resilience, fabricated ID rejection, model failure fallback, API endpoints, new source invalidation, cross-run isolation, and database migration.
  - Total 154 passing backend tests (100% offline).

---

## Quotation Auditing Technical Reference

### Outcome Taxonomy
| Outcome | Description | Criteria |
|---|---|---|
| `exact_match` | Verbatim fidelity | Exact character-for-character substring exists in supplied text or PDF page. |
| `normalized_match` | Faithful under normalization | Matches after conservative normalization (quote folding, whitespace collapse, soft hyphens). |
| `altered_quote` | Material alteration | Candidate passage exists in source with substantive differences (changed numbers, negations, or words). |
| `partial_match` | Truncated quotation | Only a fragment/prefix/suffix is present in the source (source text ends or excerpt is truncated). |
| `unverifiable` | Insufficient evidence | Quote is absent from supplied documents; source coverage is insufficient to verify or refute. |

### Quotation Authenticity vs. Factual Verification
- **Quotation Authenticity** assesses whether an author or document *verbatim said or wrote* the exact quoted words.
- **Factual Verification** assesses whether the underlying *claim is true or false*.
- **Crucial Distinction:** An altered quote may report a true fact (e.g. *"revenue was $10M"* when revenue was indeed $10M, but the author actually wrote *"turnover was $10M"*). Conversely, a completely authentic exact quote can state an untruth if the quoted source itself made an error. Second Opinion evaluates both dimensions independently.

### Limitations
- **OCR Limitations:** Image-only or scanned PDFs without embedded text cannot be searched for quotations without OCR (Phase 6/7 will alert the user).
- **Line Break Hyphenation:** Complex column layouts or non-standard hyphenation in PDFs may require model-assisted interpretation to distinguish layout artifacts from text alteration.

---

### How to Run Offline Tests
```bash
# Run complete backend test suite (154 passing tests)
cd d:\bitnbuild\backend
.\venv\Scripts\python -m pytest -v

# Run Phase 5 & Phase 7A evaluation runner
cd d:\bitnbuild\backend
.\venv\Scripts\python -m evaluation.runner

# Run frontend build and linter
cd d:\bitnbuild\frontend
npm run build
npm run lint
```

### Privacy & LLM Notice
When claim extraction, assessment, or quotation auditing is triggered, user-submitted answer text and reference source excerpts are transmitted to the configured Google Gemini API endpoint via the official `google-genai` SDK using the server-side `GEMINI_API_KEY`. Verification verdicts are evidence-grounded assessments derived strictly from the supplied reference documents—they are not guarantees of universal real-world truth.

### Explicitly Deferred to Future Phases
- **Phase 7B / 7C:** Report export (PDF/JSON download), user accounts, advanced visual polish.
- **Out of Scope for MVP:** User authentication, external web scraping, vector databases, multi-agent frameworks, OCR for scanned images.


=======
# second_opinion
>>>>>>> cbac2e49076133e07389d83439439613b356beec
