import React, { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { apiClient } from '../api/client';
import type { VerificationReportResponse, ClaimResponse } from '../types/api';

export const ReportPage: React.FC = () => {
  const { runId } = useParams<{ runId: string }>();

  const [report, setReport] = useState<VerificationReportResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(Boolean(runId));
  const [isVerifyingAll, setIsVerifyingAll] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isNotFound, setIsNotFound] = useState<boolean>(!runId);

  // Expanded states
  const [expandedSources, setExpandedSources] = useState<Record<string, boolean>>({});
  const [filterVerdict, setFilterVerdict] = useState<string>('all');

  // Additional PDF upload state
  const [showPdfUpload, setShowPdfUpload] = useState<boolean>(false);
  const [additionalPdfFile, setAdditionalPdfFile] = useState<File | null>(null);
  const [additionalPdfTitle, setAdditionalPdfTitle] = useState<string>('');
  const [isUploadingPdf, setIsUploadingPdf] = useState<boolean>(false);
  const [pdfUploadError, setPdfUploadError] = useState<string | null>(null);

  const toggleSourceExpand = (sourceId: string) => {
    setExpandedSources((prev) => ({
      ...prev,
      [sourceId]: !prev[sourceId],
    }));
  };

  const handleUploadAdditionalPdf = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!runId || !additionalPdfFile) return;

    if (!additionalPdfFile.name.toLowerCase().endsWith('.pdf')) {
      setPdfUploadError('The selected file must have a .pdf extension.');
      return;
    }
    if (additionalPdfFile.size > 10 * 1024 * 1024) {
      setPdfUploadError('PDF file size exceeds maximum limit of 10 MB.');
      return;
    }

    setIsUploadingPdf(true);
    setPdfUploadError(null);

    try {
      await apiClient.uploadPdfSource(
        runId,
        additionalPdfFile,
        additionalPdfTitle.trim() || additionalPdfFile.name
      );
      setAdditionalPdfFile(null);
      setAdditionalPdfTitle('');
      setShowPdfUpload(false);
      // Auto-run full verification on the new source
      await runFullVerification(runId);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to attach PDF source document.';
      setPdfUploadError(msg);
      setIsUploadingPdf(false);
    }
  };

  const runFullVerification = async (id: string) => {
    setIsVerifyingAll(true);
    setErrorMessage(null);
    try {
      const updatedReport = await apiClient.verifyAll(id);
      setReport(updatedReport);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Automated verification failed.';
      setErrorMessage(msg);
      // Try fetching current status
      try {
        const fallback = await apiClient.getReport(id);
        setReport(fallback);
      } catch {
        // Retain view
      }
    } finally {
      setIsVerifyingAll(false);
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!runId) return;

    let isMounted = true;
    setLoading(true);
    setErrorMessage(null);

    apiClient
      .getReport(runId)
      .then(async (data) => {
        if (!isMounted) return;
        setReport(data);
        setLoading(false);

        // If the run has claims not yet assessed, auto-run verification!
        const needsAssessment =
          data.claims.length === 0 ||
          data.claims.some((c) => c.verdict === null) ||
          data.status === 'pending';

        if (needsAssessment && !isVerifyingAll) {
          runFullVerification(runId);
        }
      })
      .catch((err: unknown) => {
        if (!isMounted) return;
        const msg = err instanceof Error ? err.message : 'Failed to retrieve report.';
        if (msg.includes('not found') || msg.includes('404')) {
          setIsNotFound(true);
        } else {
          setErrorMessage(msg);
        }
        setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [runId]);

  const filteredClaims: ClaimResponse[] = (report?.claims || []).filter((claim) => {
    if (filterVerdict === 'all') return true;
    if (filterVerdict === 'supported') return claim.verdict === 'supported';
    if (filterVerdict === 'contradicted') return claim.verdict === 'contradicted';
    if (filterVerdict === 'insufficient') return claim.verdict === 'insufficiently_supported';
    if (filterVerdict === 'ambiguous') return claim.verdict === 'ambiguous';
    return true;
  });

  return (
    <div>
      {/* Top Navigation Bar */}
      <nav className="navbar">
        <div className="nav-container">
          <div className="nav-brand">
            <Link to="/" style={{ display: 'flex', alignItems: 'center', gap: '12px', textDecoration: 'none', color: 'inherit' }}>
              <div className="nav-logo-glyph">◈</div>
              <span className="nav-brand-title">SECOND OPINION</span>
            </Link>
          </div>

          <div className="nav-actions">
            <Link to="/" className="pill-button pill-amber">
              ← New Verification
            </Link>
            {runId && (
              <button
                type="button"
                className="pill-button pill-green"
                disabled={isVerifyingAll || loading}
                onClick={() => runFullVerification(runId)}
              >
                {isVerifyingAll ? 'Auditing Claims...' : '↻ Re-Audit All'}
              </button>
            )}
            <button
              type="button"
              className="pill-button pill-blue"
              onClick={() => setShowPdfUpload(!showPdfUpload)}
            >
              + Attach Source PDF
            </button>
          </div>
        </div>
      </nav>

      {/* Main Content Column */}
      <main className="page-column">
        {/* Loading State */}
        {loading && (
          <section className="specimen-card" style={{ textAlign: 'center', padding: '64px 32px' }}>
            <div className="spinner-glyph" style={{ fontSize: '28px', color: 'var(--color-specimen-green)', marginBottom: '16px' }}>
              ⚙
            </div>
            <h2 style={{ fontSize: '22px', color: 'var(--color-ghost-white)', marginBottom: '8px' }}>
              Retrieving Verification Run...
            </h2>
            <p className="prose-text" style={{ color: 'var(--color-mist)' }}>
              Querying immutable database records and source fingerprints for run {runId}
            </p>
          </section>
        )}

        {/* 404 Not Found State */}
        {!loading && isNotFound && (
          <section className="specimen-card" style={{ textAlign: 'center', padding: '64px 32px' }}>
            <div style={{ fontSize: '36px', marginBottom: '16px' }}>🔍</div>
            <h2 style={{ fontSize: '24px', color: 'var(--color-ghost-white)', marginBottom: '12px' }}>
              Verification Record Not Found
            </h2>
            <p className="prose-text" style={{ color: 'var(--color-mist)', marginBottom: '24px' }}>
              No audit records exist for run ID <code>{runId}</code>.
            </p>
            <Link to="/" className="pill-button pill-green">
              Return to Verification Terminal
            </Link>
          </section>
        )}

        {/* Server Error State */}
        {!loading && errorMessage && !isNotFound && (
          <section className="specimen-alert specimen-alert-danger" role="alert">
            <span>▲</span>
            <div style={{ flex: 1 }}>
              <strong>Audit Error:</strong> {errorMessage}
            </div>
            {runId && (
              <button
                type="button"
                className="pill-button pill-red"
                onClick={() => runFullVerification(runId)}
              >
                Retry
              </button>
            )}
          </section>
        )}

        {/* Additional PDF Ingestion Drawer */}
        {showPdfUpload && (
          <section className="specimen-card" style={{ border: '1px solid rgba(99, 179, 237, 0.3)' }}>
            <div className="section-heading" style={{ fontSize: '18px', marginBottom: '16px' }}>
              <span className="heading-glyph">⚙</span> Attach Ground-Truth PDF Document
            </div>

            {pdfUploadError && (
              <div className="specimen-alert specimen-alert-danger" style={{ marginBottom: '16px' }}>
                {pdfUploadError}
              </div>
            )}

            <form onSubmit={handleUploadAdditionalPdf}>
              <div style={{ marginBottom: '16px' }}>
                <label style={{ fontSize: '13px', color: 'var(--color-mist)', display: 'block', marginBottom: '6px' }}>
                  Document Title:
                </label>
                <input
                  type="text"
                  className="terminal-input-single"
                  value={additionalPdfTitle}
                  onChange={(e) => setAdditionalPdfTitle(e.target.value)}
                  placeholder="e.g. Supplemental Field Guidelines.pdf"
                />
              </div>

              <div style={{ marginBottom: '16px' }}>
                <input
                  type="file"
                  accept=".pdf,application/pdf"
                  className="terminal-input-single"
                  onChange={(e) => {
                    const file = e.target.files?.[0] || null;
                    setAdditionalPdfFile(file);
                    if (file && !additionalPdfTitle) {
                      setAdditionalPdfTitle(file.name);
                    }
                  }}
                />
              </div>

              <div style={{ display: 'flex', gap: '12px' }}>
                <button
                  type="submit"
                  className="pill-button pill-green"
                  disabled={isUploadingPdf || !additionalPdfFile}
                >
                  {isUploadingPdf ? 'Uploading & Parsing...' : 'Attach & Re-Audit'}
                </button>
                <button
                  type="button"
                  className="pill-button pill-amber"
                  onClick={() => setShowPdfUpload(false)}
                >
                  Cancel
                </button>
              </div>
            </form>
          </section>
        )}

        {/* Verification Report Display */}
        {!loading && report && (
          <>
            {/* Header Telemetry Status Bar */}
            <section className="specimen-card" style={{ padding: '24px 32px' }}>
              <div className="card-header-bar">
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <span className="heading-glyph">⚙</span>
                  <h1 style={{ fontSize: '20px', fontWeight: 400, color: 'var(--color-ghost-white)', margin: 0 }}>
                    Audited Verification Report
                  </h1>
                </div>
                <span className="card-metadata">
                  ID: <code style={{ color: 'var(--color-portal-blue)' }}>{report.run_id}</code>
                </span>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
                <div className={`verdict-specimen-badge ${
                  report.status === 'completed' ? 'badge-supported' : 'badge-ambiguous'
                }`}>
                  {report.status.toUpperCase()}
                </div>
                <span style={{ fontSize: '14px', color: 'var(--color-mist)' }}>
                  {report.summary.coverage_note}
                </span>
              </div>
            </section>

            {/* Specimen Metrics Taxonomy Bar */}
            <section className="metrics-specimen-bar">
              <div
                className="metric-specimen-cell"
                style={{ cursor: 'pointer', border: filterVerdict === 'all' ? '1px solid var(--color-fog)' : undefined }}
                onClick={() => setFilterVerdict('all')}
              >
                <div className="metric-value">{report.summary.total_claims}</div>
                <div className="metric-label">Total Claims</div>
              </div>

              <div
                className="metric-specimen-cell"
                style={{
                  cursor: 'pointer',
                  border: filterVerdict === 'supported' ? '1px solid var(--color-specimen-green)' : undefined,
                  boxShadow: filterVerdict === 'supported' ? 'var(--glow-green)' : undefined
                }}
                onClick={() => setFilterVerdict('supported')}
              >
                <div className="metric-value" style={{ color: 'var(--color-specimen-green)' }}>
                  {report.summary.supported}
                </div>
                <div className="metric-label">Correct / Supported</div>
              </div>

              <div
                className="metric-specimen-cell"
                style={{
                  cursor: 'pointer',
                  border: filterVerdict === 'contradicted' ? '1px solid var(--color-fault-red)' : undefined,
                  boxShadow: filterVerdict === 'contradicted' ? 'var(--glow-red)' : undefined
                }}
                onClick={() => setFilterVerdict('contradicted')}
              >
                <div className="metric-value" style={{ color: 'var(--color-fault-red)' }}>
                  {report.summary.contradicted}
                </div>
                <div className="metric-label">Contradicted</div>
              </div>

              <div
                className="metric-specimen-cell"
                style={{
                  cursor: 'pointer',
                  border: filterVerdict === 'insufficient' ? '1px solid var(--color-warning-amber)' : undefined,
                  boxShadow: filterVerdict === 'insufficient' ? 'var(--glow-amber)' : undefined
                }}
                onClick={() => setFilterVerdict('insufficient')}
              >
                <div className="metric-value" style={{ color: 'var(--color-warning-amber)' }}>
                  {report.summary.insufficiently_supported}
                </div>
                <div className="metric-label">Insufficient Evidence</div>
              </div>

              <div
                className="metric-specimen-cell"
                style={{
                  cursor: 'pointer',
                  border: filterVerdict === 'ambiguous' ? '1px solid var(--color-portal-blue)' : undefined,
                  boxShadow: filterVerdict === 'ambiguous' ? 'var(--glow-blue)' : undefined
                }}
                onClick={() => setFilterVerdict('ambiguous')}
              >
                <div className="metric-value" style={{ color: 'var(--color-portal-blue)' }}>
                  {report.summary.ambiguous}
                </div>
                <div className="metric-label">Ambiguous</div>
              </div>
            </section>

            {/* Original AI Answer Section */}
            <section className="specimen-card">
              <div className="section-heading" style={{ fontSize: '18px', marginBottom: '12px' }}>
                <span className="heading-glyph">ℹ</span> Audited AI Answer
              </div>
              <div
                style={{
                  backgroundColor: 'var(--color-cosmic-void)',
                  padding: '16px',
                  borderRadius: '8px',
                  fontSize: '15px',
                  lineHeight: '1.6',
                  color: 'var(--color-mist)',
                  border: '1px solid rgba(229, 231, 235, 0.08)',
                  whiteSpace: 'pre-wrap',
                }}
              >
                {report.original_answer}
              </div>
            </section>

            {/* Categorized Factual Claims Section */}
            <section>
              <div className="section-heading" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span className="heading-glyph">✦</span>
                  <span>Factual Claims & Categorization</span>
                  <span style={{ fontSize: '14px', color: 'var(--color-mist)', opacity: 0.7 }}>
                    ({filteredClaims.length} of {report.claims.length})
                  </span>
                </div>

                {filterVerdict !== 'all' && (
                  <button
                    type="button"
                    className="pill-button pill-amber"
                    onClick={() => setFilterVerdict('all')}
                    style={{ fontSize: '12px', padding: '4px 12px' }}
                  >
                    Clear Filter
                  </button>
                )}
              </div>

              {filteredClaims.length === 0 ? (
                <div className="specimen-card" style={{ textAlign: 'center', padding: '32px' }}>
                  <p className="prose-text" style={{ color: 'var(--color-mist)' }}>
                    No claims match the selected verdict filter.
                  </p>
                </div>
              ) : (
                filteredClaims.map((claim, idx) => {
                  let badgeClass = 'badge-insufficient';
                  let verdictLabel = 'Insufficient Evidence';

                  if (claim.verdict === 'supported') {
                    badgeClass = 'badge-supported';
                    verdictLabel = 'Supported / Correct';
                  } else if (claim.verdict === 'contradicted') {
                    badgeClass = 'badge-contradicted';
                    verdictLabel = 'Contradicted';
                  } else if (claim.verdict === 'ambiguous') {
                    badgeClass = 'badge-ambiguous';
                    verdictLabel = 'Ambiguous';
                  }

                  return (
                    <article key={claim.id} className="claim-specimen-card">
                      <div className="claim-header-row">
                        <span className="claim-index-tag">
                          SPECIMEN #{idx + 1}
                        </span>
                        <div className={`verdict-specimen-badge ${badgeClass}`}>
                          {verdictLabel}
                        </div>
                      </div>

                      {/* Normalized Claim Statement */}
                      <div className="claim-statement-text">
                        "{claim.normalized_text}"
                      </div>

                      {/* Reasoning Analysis */}
                      {claim.reasoning && (
                        <div className="claim-reasoning-panel">
                          <strong style={{ color: 'var(--color-ghost-white)', display: 'block', marginBottom: '4px' }}>
                            Auditor Grounded Assessment:
                          </strong>
                          <p style={{ margin: 0, lineHeight: 1.5 }}>{claim.reasoning}</p>
                          {claim.limitations && (
                            <p style={{ marginTop: '8px', fontSize: '13px', color: 'var(--color-warning-amber)' }}>
                              ⚠ Limitations: {claim.limitations}
                            </p>
                          )}
                        </div>
                      )}

                      {/* Cited Evidence Passages */}
                      {claim.evidence && claim.evidence.length > 0 && (
                        <div>
                          <span style={{ fontSize: '12px', color: 'var(--color-mist)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                            Cited Reference Evidence ({claim.evidence.length} passage{claim.evidence.length > 1 ? 's' : ''}):
                          </span>
                          {claim.evidence.map((ev) => (
                            <div key={ev.id} className="evidence-passage-box">
                              <div className="evidence-source-tag">
                                <span>📄 {ev.source_title}</span>
                                {ev.page_number && <span>• Page {ev.page_number}</span>}
                                {ev.relevance_score && (
                                  <span style={{ color: 'var(--color-specimen-green)' }}>
                                    • BM25 Score: {ev.relevance_score.toFixed(2)}
                                  </span>
                                )}
                              </div>
                              <div style={{ color: 'var(--color-ice-blue)', fontStyle: 'italic', marginBottom: '6px' }}>
                                "{ev.excerpt}"
                              </div>
                              {ev.explanation && (
                                <div style={{ fontSize: '12px', color: 'var(--color-mist)', opacity: 0.85 }}>
                                  Correlation: {ev.explanation}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      )}

                      {(!claim.evidence || claim.evidence.length === 0) && (
                        <div style={{ fontSize: '13px', color: 'var(--color-mist)', opacity: 0.65, fontStyle: 'italic', marginTop: '8px' }}>
                          No qualifying evidence passage was located in user-supplied reference material.
                        </div>
                      )}
                    </article>
                  );
                })
              )}
            </section>

            {/* Direct Quotation Audits Section */}
            {report.quote_audits && report.quote_audits.length > 0 && (
              <section className="specimen-card">
                <div className="section-heading" style={{ fontSize: '18px', marginBottom: '16px' }}>
                  <span className="heading-glyph">⚙</span> Direct Quotation Audits
                </div>
                <p className="prose-text" style={{ fontSize: '14px', color: 'var(--color-mist)', marginBottom: '16px' }}>
                  Verifies whether quoted strings in the original AI reply appear verbatim in reference material:
                </p>

                {report.quote_audits.map((qa) => (
                  <div
                    key={qa.id}
                    style={{
                      backgroundColor: 'var(--color-cosmic-void)',
                      border: '1px solid rgba(229, 231, 235, 0.08)',
                      borderRadius: '8px',
                      padding: '16px',
                      marginBottom: '12px',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                      <span style={{ fontSize: '13px', color: 'var(--color-mist)' }}>
                        Quotation: <strong style={{ color: 'var(--color-ghost-white)' }}>"{qa.quotation_text}"</strong>
                      </span>
                      <span className={`verdict-specimen-badge ${
                        qa.match_status === 'exact_match' ? 'badge-supported' : 'badge-contradicted'
                      }`}>
                        {qa.match_status.replace('_', ' ').toUpperCase()}
                      </span>
                    </div>

                    {qa.matched_source_title && (
                      <div style={{ fontSize: '13px', color: 'var(--color-portal-blue)', marginBottom: '4px' }}>
                        Source: {qa.matched_source_title} {qa.page_number ? `(Page ${qa.page_number})` : ''}
                      </div>
                    )}
                    {qa.source_excerpt && (
                      <div style={{ fontSize: '13px', color: 'var(--color-mist)', fontStyle: 'italic' }}>
                        Source text: "{qa.source_excerpt}"
                      </div>
                    )}
                    {qa.differences && (
                      <div style={{ fontSize: '12px', color: 'var(--color-fault-red)', marginTop: '4px' }}>
                        Discrepancy: {qa.differences}
                      </div>
                    )}
                  </div>
                ))}
              </section>
            )}

            {/* Ground-Truth Reference Document Inspector */}
            <section className="specimen-card">
              <div className="section-heading" style={{ fontSize: '18px', marginBottom: '16px' }}>
                <span className="heading-glyph">ℹ</span> Preserved Reference Documents
              </div>

              {report.sources.map((src) => {
                const isExpanded = expandedSources[src.id];
                return (
                  <div key={src.id} className="source-inspector-card">
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px', flexWrap: 'wrap', gap: '8px' }}>
                      <strong style={{ color: 'var(--color-ghost-white)', fontSize: '15px' }}>
                        {src.title}
                      </strong>
                      <button
                        type="button"
                        className="pill-button pill-amber"
                        onClick={() => toggleSourceExpand(src.id)}
                        style={{ fontSize: '12px', padding: '4px 12px' }}
                      >
                        {isExpanded ? 'Hide Full Content' : 'Inspect Full Text'}
                      </button>
                    </div>

                    <div className="source-fingerprint" style={{ marginBottom: '8px' }}>
                      SHA-256: {src.content_hash} • {src.content_length} characters • Type: {src.source_type.toUpperCase()}
                      {src.page_count ? ` • ${src.page_count} pages` : ''}
                    </div>

                    {isExpanded && (
                      <div
                        style={{
                          marginTop: '12px',
                          padding: '16px',
                          backgroundColor: 'var(--color-cosmic-void)',
                          borderRadius: '8px',
                          fontSize: '13px',
                          maxHeight: '360px',
                          overflowY: 'auto',
                          whiteSpace: 'pre-wrap',
                          border: '1px solid rgba(229, 231, 235, 0.08)',
                          color: 'var(--color-mist)',
                        }}
                      >
                        {src.content}
                      </div>
                    )}
                  </div>
                );
              })}
            </section>

            {/* Scope Disclaimer */}
            <footer style={{ textAlign: 'center', fontSize: '13px', color: 'var(--color-mist)', opacity: 0.65, paddingTop: '16px' }}>
              {report.scope_disclaimer}
            </footer>
          </>
        )}
      </main>
    </div>
  );
};
