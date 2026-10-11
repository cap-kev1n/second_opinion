/**
 * Dedicated HTTP API Client for Second Opinion backend.
 * Provides typed methods and handles connection failures cleanly.
 */

import type {
  HealthResponse,
  RunCreateRequest,
  RunStatusResponse,
  VerificationReportResponse,
  SourceResponse,
  ApiError,
} from '../types/api';

// On deployed Vercel origins or with a local dev proxy, relative paths ('') allow requests to route through Vercel rewrites.
// If VITE_API_BASE_URL is set, it will be prioritized. In standalone development without proxy, localhost:8000 is used.
const DEFAULT_BASE_URL = import.meta.env.DEV ? 'http://localhost:8000' : '';

export class ApiClient {
  private baseUrl: string;

  constructor(baseUrl?: string) {
    if (baseUrl !== undefined) {
      this.baseUrl = baseUrl;
    } else if (import.meta.env.VITE_API_BASE_URL !== undefined && import.meta.env.VITE_API_BASE_URL !== '') {
      this.baseUrl = import.meta.env.VITE_API_BASE_URL as string;
    } else {
      this.baseUrl = DEFAULT_BASE_URL;
    }
  }

  public getBaseUrl(): string {
    return this.baseUrl;
  }

  /**
   * Health check endpoint to verify backend connectivity.
   */
  async checkHealth(): Promise<HealthResponse> {
    const response = await fetch(`${this.baseUrl}/api/health`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
      },
    });

    if (!response.ok) {
      const errorData = (await response.json().catch(() => null)) as ApiError | null;
      throw new Error(errorData?.detail || `Health check failed (${response.status})`);
    }

    return response.json();
  }

  /**
   * Initiates a verification run.
   */
  async createRun(payload: RunCreateRequest): Promise<RunStatusResponse> {
    const response = await fetch(`${this.baseUrl}/api/runs`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const errorData = (await response.json().catch(() => null)) as ApiError | null;
      throw new Error(errorData?.detail || `Run creation failed (${response.status})`);
    }

    return response.json();
  }

  /**
   * Initiates a verification run with an uploaded PDF reference document.
   */
  async createRunWithPdf(answer: string, file: File, title?: string): Promise<RunStatusResponse> {
    const formData = new FormData();
    formData.append('answer', answer);
    formData.append('file', file);
    if (title && title.trim()) {
      formData.append('title', title.trim());
    }

    const response = await fetch(`${this.baseUrl}/api/runs/upload-pdf`, {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
      },
      body: formData,
    });

    if (!response.ok) {
      const errorData = (await response.json().catch(() => null)) as ApiError | null;
      throw new Error(errorData?.detail || `PDF Run creation failed (${response.status})`);
    }

    return response.json();
  }

  /**
   * Uploads and attaches a PDF reference document to an existing run.
   */
  async uploadPdfSource(runId: string, file: File, title?: string): Promise<SourceResponse> {
    const formData = new FormData();
    formData.append('file', file);
    if (title && title.trim()) {
      formData.append('title', title.trim());
    }

    const response = await fetch(`${this.baseUrl}/api/runs/${runId}/sources/pdf`, {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
      },
      body: formData,
    });

    if (!response.ok) {
      const errorData = (await response.json().catch(() => null)) as ApiError | null;
      if (response.status === 409) {
        throw new Error(errorData?.detail || 'Cannot upload PDF while run is actively processing.');
      }
      throw new Error(errorData?.detail || `PDF upload failed (${response.status})`);
    }

    return response.json();
  }

  /**
   * Fetches and attaches a website URL reference document to an existing run.
   */
  async attachUrlSource(runId: string, url: string, title?: string): Promise<SourceResponse> {
    const response = await fetch(`${this.baseUrl}/api/runs/${runId}/sources/url`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify({
        url: url.trim(),
        title: title?.trim() || '',
        source_type: 'url',
      }),
    });

    if (!response.ok) {
      const errorData = (await response.json().catch(() => null)) as ApiError | null;
      if (response.status === 409) {
        throw new Error(errorData?.detail || 'Cannot attach URL source while run is actively processing.');
      }
      throw new Error(errorData?.detail || `URL source attachment failed (${response.status})`);
    }

    return response.json();
  }

  /**
   * Retrieves lifecycle status for an existing verification run.
   */
  async getRunStatus(runId: string): Promise<RunStatusResponse> {
    const response = await fetch(`${this.baseUrl}/api/runs/${runId}/status`, {
      method: 'GET',
      headers: { 'Accept': 'application/json' },
    });

    if (!response.ok) {
      const errorData = (await response.json().catch(() => null)) as ApiError | null;
      if (response.status === 404) {
        throw new Error(errorData?.detail || `Verification run '${runId}' was not found.`);
      }
      throw new Error(errorData?.detail || `Failed to fetch status for run ${runId} (${response.status})`);
    }

    return response.json();
  }

  /**
   * Fetches auditable verification report for a run.
   */
  async getReport(runId: string): Promise<VerificationReportResponse> {
    const response = await fetch(`${this.baseUrl}/api/runs/${runId}/report`, {
      method: 'GET',
      headers: { 'Accept': 'application/json' },
    });

    if (!response.ok) {
      const errorData = (await response.json().catch(() => null)) as ApiError | null;
      if (response.status === 404) {
        throw new Error(errorData?.detail || `Verification run '${runId}' was not found.`);
      }
      throw new Error(errorData?.detail || `Failed to fetch report for run ${runId} (${response.status})`);
    }

    return response.json();
  }

  /**
   * Triggers atomic factual claim extraction for a run using Gemini.
   */
  async extractClaims(runId: string): Promise<VerificationReportResponse> {
    const response = await fetch(`${this.baseUrl}/api/runs/${runId}/extract`, {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
      },
    });

    if (!response.ok) {
      const errorData = (await response.json().catch(() => null)) as ApiError | null;
      if (response.status === 404) {
        throw new Error(errorData?.detail || `Verification run '${runId}' was not found.`);
      }
      if (response.status === 409) {
        throw new Error(errorData?.detail || 'Claim extraction is already in progress.');
      }
      throw new Error(errorData?.detail || `Claim extraction failed (${response.status})`);
    }

    return response.json();
  }

  /**
   * Triggers BM25 candidate passage retrieval from user sources for a run's claims.
   */
  async retrieveEvidence(runId: string, topK?: number): Promise<VerificationReportResponse> {
    const url = topK
      ? `${this.baseUrl}/api/runs/${runId}/retrieve?top_k=${topK}`
      : `${this.baseUrl}/api/runs/${runId}/retrieve`;

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
      },
    });

    if (!response.ok) {
      const errorData = (await response.json().catch(() => null)) as ApiError | null;
      if (response.status === 404) {
        throw new Error(errorData?.detail || `Verification run '${runId}' was not found.`);
      }
      if (response.status === 409) {
        throw new Error(errorData?.detail || 'Evidence retrieval is already in progress.');
      }
      if (response.status === 400) {
        throw new Error(errorData?.detail || 'Claim extraction must be completed before retrieving evidence.');
      }
      throw new Error(errorData?.detail || `Evidence retrieval failed (${response.status})`);
    }

    return response.json();
  }

  /**
   * Triggers evidence-grounded claim assessment via Gemini for a run.
   */
  async assessClaims(runId: string, forceReassess: boolean = false): Promise<VerificationReportResponse> {
    const url = forceReassess
      ? `${this.baseUrl}/api/runs/${runId}/assess?force_reassess=true`
      : `${this.baseUrl}/api/runs/${runId}/assess`;

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
      },
    });

    if (!response.ok) {
      const errorData = (await response.json().catch(() => null)) as ApiError | null;
      if (response.status === 404) {
        throw new Error(errorData?.detail || `Verification run '${runId}' was not found.`);
      }
      if (response.status === 409) {
        throw new Error(errorData?.detail || 'Claim assessment is already in progress.');
      }
      if (response.status === 400) {
        throw new Error(errorData?.detail || 'Evidence retrieval must be completed before assessing claims.');
      }
      throw new Error(errorData?.detail || `Claim assessment failed (${response.status})`);
    }

    return response.json();
  }

  /**
   * Fetches exact source content and metadata for a specific source.
   */
  async getSource(runId: string, sourceId: string): Promise<SourceResponse> {
    const response = await fetch(`${this.baseUrl}/api/runs/${runId}/sources/${sourceId}`, {
      method: 'GET',
      headers: { 'Accept': 'application/json' },
    });

    if (!response.ok) {
      const errorData = (await response.json().catch(() => null)) as ApiError | null;
      throw new Error(errorData?.detail || `Failed to fetch source (${response.status})`);
    }

    return response.json();
  }

  /**
   * Audits candidate direct quotations in original answer against reference material.
   */
  async auditQuotes(runId: string): Promise<VerificationReportResponse> {
    const response = await fetch(`${this.baseUrl}/api/runs/${runId}/audit-quotes`, {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
      },
    });

    if (!response.ok) {
      const errorData = (await response.json().catch(() => null)) as ApiError | null;
      if (response.status === 404) {
        throw new Error(errorData?.detail || `Verification run '${runId}' was not found.`);
      }
      throw new Error(errorData?.detail || `Quotation audit failed (${response.status})`);
    }

    return response.json();
  }

  /**
   * Executes entire automated verification pipeline in one call:
   * Claim Extraction -> BM25 Lexical Evidence Retrieval -> Grounded Assessment & Quote Audit.
   */
  async verifyAll(runId: string): Promise<VerificationReportResponse> {
    const response = await fetch(`${this.baseUrl}/api/runs/${runId}/verify-all`, {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
      },
    });

    if (!response.ok) {
      // Fallback sequentially if server is legacy or returned error
      try {
        await this.extractClaims(runId);
        await this.retrieveEvidence(runId);
        return await this.assessClaims(runId);
      } catch (fallbackErr) {
        const errorData = (await response.json().catch(() => null)) as ApiError | null;
        throw new Error(
          errorData?.detail ||
          (fallbackErr instanceof Error ? fallbackErr.message : `Full verification pipeline failed (${response.status})`)
        );
      }
    }

    return response.json();
  }
}

// Global API client instance
export const apiClient = new ApiClient();
