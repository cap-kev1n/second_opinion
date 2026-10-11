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

  // Minimalist Per-Claim Expansion state (collapsed by default)
  const [expandedClaims, setExpandedClaims] = useState<Record<string, boolean>>({});
  const [expandedSources, setExpandedSources] = useState<Record<string, boolean>>({});
  const [filterVerdict, setFilterVerdict] = useState<string>('all');

  // Additional PDF upload state
  const [showPdfUpload, setShowPdfUpload] = useState<boolean>(false);
  const [additionalPdfFile, setAdditionalPdfFile] = useState<File | null>(null);
  const [additionalPdfTitle, setAdditionalPdfTitle] = useState<string>('');
  const [isUploadingPdf, setIsUploadingPdf] = useState<boolean>(false);
  const [pdfUploadError, setPdfUploadError] = useState<string | null>(null);

  const toggleClaimExpand = (claimId: string) => {
    setExpandedClaims((prev) => ({
      ...prev,
      [claimId]: !prev[claimId],
    }));
  };

  const toggleSourceExpand = (sourceId: string) => {
    setExpandedSources((prev) => ({
      ...prev,
      [sourceId]: !prev[sourceId],
    }));
  };

  const handleToggleExpandAll = () => {
    if (!report) return;
    const allExpanded = report.claims.every((c) => expandedClaims[c.id]);
    if (allExpanded) {
      setExpandedClaims({});
    } else {
      const next: Record<string, boolean> = {};
      report.claims.forEach((c) => {
        next[c.id] = true;
      });
      setExpandedClaims(next);
    }
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
      try {
        const fallback = await apiClient.getReport(id);
        setReport(fallback);
      } catch {
        // Retain current view
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

  const areAllClaimsExpanded =
    report && report.claims.length > 0 && report.claims.every((c) => expandedClaims[c.id]);

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
            <Link to="/" className="pill-button pill-mint">
              ← New Verification
            </Link>
            {runId && (
              <button
                type="button"
                className="pill-button pill-ember"
                disabled={isVerifyingAll || loading}
                onClick={() => runFullVerification(runId)}
              >
                {isVerifyingAll ? 'Auditing Claims...' : '↻ Re-Audit All'}
              </button>
            )}
            <button
              type="button"
              className="pill-button"
              style={{
                color: 'var(--color-cream-text)',
                borderColor: 'var(--color-iron-border)',
                background: 'transparent',
              }}
              onClick={() => setShowPdfUpload(!showPdfUpload)}
            >
              + Attach PDF
            </button>
          </div>
        </div>
      </nav>

      {/* Main Content Column */}
      <main className="page-column desktop-wide">
        {/* Loading State */}
        {loading && (
          <section className="specimen-card" style={{ textAlign: 'center', padding: '64px 32px' }}>
            <div className="spinner-glyph" style={{ fontSize: '28px', color: 'var(--color-mint-pulse)', marginBottom: '16px' }}>
              ⚙
            </div>
            <h2 style={{ fontSize: '18px', fontWeight: 400, color: 'var(--color-cream-text)', marginBottom: '8px' }}>
              Retrieving Verification Specimen
            </h2>
            <p className="prose-text" style={{ color: 'var(--color-zinc-mute)', fontSize: '14px' }}>
              Fetching claim categorizations, source hashes, and evidence passages...
            </p>
          </section>
        )}

        {/* Not Found State */}
        {!loading && isNotFound && (
          <section className="specimen-card" style={{ textAlign: 'center', padding: '64px 32px' }}>
            <div style={{ fontSize: '32px', color: 'var(--color-ember-orange)', marginBottom: '16px' }}>
              ⚠
            </div>
            <h2 style={{ fontSize: '20px', fontWeight: 400, color: 'var(--color-cream-text)', marginBottom: '8px' }}>
              Audit Report Not Found
            </h2>
            <p className="prose-text" style={{ color: 'var(--color-zinc-mute)', marginBottom: '24px' }}>
              No audit run was identified for ID: <code>{runId}</code>.
            </p>
            <Link to="/" className="pill-button pill-ember">
              Return to Verification Console
            </Link>
          </section>
        )}

        {/* System Fault Alert */}
        {errorMessage && (
          <div className="specimen-alert specimen-alert-danger" role="alert">
            <span>▲</span>
            <div>
              <strong>SYSTEM NOTICE:</strong> {errorMessage}
            </div>
          </div>
        )}

        {/* Additional PDF Source Drawer */}
        {showPdfUpload && (
          <section className="specimen-card" style={{ marginBottom: 'var(--spacing-16)' }}>
            <div className="card-header-bar">
              <span className="card-label">ATTACH SUPPLEMENTAL REFERENCE PDF</span>
              <button
                type="button"
                onClick={() => setShowPdfUpload(false)}
                style={{ background: 'none', border: 'none', color: 'var(--color-zinc-mute)', cursor: 'pointer', fontSize: '13px' }}
              >
                ✕ Close
              </button>
            </div>

            {pdfUploadError && (
              <div className="specimen-alert specimen-alert-danger" style={{ marginBottom: '16px' }}>
                <span>⚠</span>
                <div>{pdfUploadError}</div>
              </div>
            )}

            <form onSubmit={handleUploadAdditionalPdf}>
              <div style={{ marginBottom: '12px' }}>
                <input
                  type="text"
                  className="terminal-input-single"
                  value={additionalPdfTitle}
                  onChange={(e) => setAdditionalPdfTitle(e.target.value)}
                  placeholder="Optional document title (e.g. Reference Manual Vol 2.pdf)"
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
                  className="pill-button pill-mint"
                  disabled={isUploadingPdf || !additionalPdfFile}
                >
                  {isUploadingPdf ? 'Uploading & Parsing...' : 'Attach & Re-Audit'}
                </button>
                <button
                  type="button"
                  className="pill-button"
                  style={{ color: 'var(--color-zinc-mute)', borderColor: 'var(--color-iron-border)', background: 'transparent' }}
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
            <section className="specimen-card" style={{ padding: '20px 24px', marginBottom: 'var(--spacing-16)' }}>
              <div className="card-header-bar" style={{ marginBottom: '12px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <span style={{ color: 'var(--color-mint-pulse)' }}>◈</span>
                  <h1 style={{ fontSize: '18px', fontWeight: 300, color: 'var(--color-cream-text)', margin: 0, letterSpacing: '0.02em' }}>
                    AUDIT REPORT
                  </h1>
                </div>
                <span className="card-metadata">
                  ID: <code style={{ color: 'var(--color-cream-text)' }}>{report.run_id}</code>
                </span>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <div className={`verdict-specimen-badge ${
                    report.status === 'completed' ? 'badge-supported' : 'badge-ambiguous'
                  }`}>
                    {report.status.toUpperCase()}
                  </div>
                  <span style={{ fontSize: '13px', color: 'var(--color-zinc-mute)' }}>
                    {report.summary.coverage_note}
                  </span>
                </div>

                <div style={{ fontSize: '12px', fontFamily: 'var(--font-geist-mono)', color: 'var(--color-zinc-mute)' }}>
                  CREATED: {new Date(report.created_at).toLocaleTimeString()}
                </div>
              </div>
            </section>

            {/* Specimen Metrics Filter Bar */}
            <section className="metrics-specimen-bar">
              <div
                className="metric-specimen-cell"
                style={{
                  cursor: 'pointer',
                  borderColor: filterVerdict === 'all' ? 'var(--color-cream-text)' : undefined,
                  background: filterVerdict === 'all' ? 'var(--color-slab-elevated)' : undefined,
                }}
                onClick={() => setFilterVerdict('all')}
                title="View all claims"
              >
                <div className="metric-value">{report.summary.total_claims}</div>
                <div className="metric-label">Total Claims</div>
              </div>

              <div
                className="metric-specimen-cell"
                style={{
                  cursor: 'pointer',
                  borderColor: filterVerdict === 'supported' ? 'var(--color-mint-pulse)' : undefined,
                  background: filterVerdict === 'supported' ? 'var(--color-slab-elevated)' : undefined,
                }}
                onClick={() => setFilterVerdict('supported')}
                title="Filter by Supported"
              >
                <div className="metric-value" style={{ color: 'var(--color-mint-pulse)' }}>
                  {report.summary.supported}
                </div>
                <div className="metric-label">Supported</div>
              </div>

              <div
                className="metric-specimen-cell"
                style={{
                  cursor: 'pointer',
                  borderColor: filterVerdict === 'contradicted' ? 'var(--color-ember-orange)' : undefined,
                  background: filterVerdict === 'contradicted' ? 'var(--color-slab-elevated)' : undefined,
                }}
                onClick={() => setFilterVerdict('contradicted')}
                title="Filter by Contradicted"
              >
                <div className="metric-value" style={{ color: 'var(--color-ember-orange)' }}>
                  {report.summary.contradicted}
                </div>
                <div className="metric-label">Contradicted</div>
              </div>

              <div
                className="metric-specimen-cell"
                style={{
                  cursor: 'pointer',
                  borderColor: filterVerdict === 'insufficient' ? '#f59e0b' : undefined,
                  background: filterVerdict === 'insufficient' ? 'var(--color-slab-elevated)' : undefined,
                }}
                onClick={() => setFilterVerdict('insufficient')}
                title="Filter by Insufficient Evidence"
              >
                <div className="metric-value" style={{ color: '#f59e0b' }}>
                  {report.summary.insufficiently_supported}
                </div>
                <div className="metric-label">Insufficient</div>
              </div>

              <div
                className="metric-specimen-cell"
                style={{
                  cursor: 'pointer',
                  borderColor: filterVerdict === 'ambiguous' ? '#38bdf8' : undefined,
                  background: filterVerdict === 'ambiguous' ? 'var(--color-slab-elevated)' : undefined,
                }}
                onClick={() => setFilterVerdict('ambiguous')}
                title="Filter by Ambiguous"
              >
                <div className="metric-value" style={{ color: '#38bdf8' }}>
                  {report.summary.ambiguous}
                </div>
                <div className="metric-label">Ambiguous</div>
              </div>
            </section>

            {/* Collapsible: Audited AI Answer (Clean Minimalist — Collapsed by default) */}
            <details className="minimal-collapse-card" style={{ marginBottom: 'var(--spacing-16)' }}>
              <summary className="minimal-collapse-summary">
                <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span>▸</span>
                  <span>ORIGINAL AI ANSWER</span>
                  <span style={{ opacity: 0.6, fontSize: '11px' }}>
                    ({report.original_answer.length} characters)
                  </span>
                </span>
                <span style={{ color: 'var(--color-zinc-mute)', fontSize: '11px' }}>
                  CLICK TO VIEW FULL TEXT
                </span>
              </summary>
              <div className="minimal-collapse-content">
                <div
                  style={{
                    backgroundColor: 'var(--color-void-canvas)',
                    padding: '16px',
                    borderRadius: '5.6px',
                    fontSize: '14px',
                    lineHeight: '1.6',
                    color: 'var(--color-cream-text)',
                    border: '1px solid var(--color-iron-border)',
                    whiteSpace: 'pre-wrap',
                    maxHeight: '380px',
                    overflowY: 'auto',
                  }}
                >
                  {report.original_answer}
                </div>
              </div>
            </details>

            {/* Collapsible: Preserved Reference Documents (Collapsed by default) */}
            <details className="minimal-collapse-card" style={{ marginBottom: 'var(--spacing-16)' }}>
              <summary className="minimal-collapse-summary">
                <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span>▸</span>
                  <span>ATTACHED REFERENCE SOURCES</span>
                  <span style={{ opacity: 0.6, fontSize: '11px' }}>
                    ({report.sources.length} document{report.sources.length > 1 ? 's' : ''})
                  </span>
                </span>
                <span style={{ color: 'var(--color-zinc-mute)', fontSize: '11px' }}>
                  CLICK TO VIEW SOURCES
                </span>
              </summary>
              <div className="minimal-collapse-content">
                {report.sources.map((src) => {
                  const isSrcExpanded = expandedSources[src.id];
                  return (
                    <div
                      key={src.id}
                      style={{
                        backgroundColor: 'var(--color-void-canvas)',
                        border: '1px solid var(--color-iron-border)',
                        borderRadius: '5.6px',
                        padding: '12px 16px',
                        marginBottom: '8px',
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
                        <div>
                          <strong style={{ color: 'var(--color-cream-text)', fontSize: '14px' }}>
                            {src.title}
                          </strong>
                          <div style={{ fontSize: '11px', fontFamily: 'var(--font-geist-mono)', color: 'var(--color-zinc-mute)', marginTop: '2px' }}>
                            TYPE: {src.source_type.toUpperCase()} • LENGTH: {src.content_length} CHARS
                            {src.page_count ? ` • ${src.page_count} PAGES` : ''}
                            {src.content_hash ? ` • HASH: ${src.content_hash.slice(0, 12)}...` : ''}
                          </div>
                        </div>

                        {src.content && (
                          <button
                            type="button"
                            className="minimal-claim-expand-btn"
                            onClick={() => toggleSourceExpand(src.id)}
                          >
                            {isSrcExpanded ? 'Hide Full Content ▴' : 'Inspect Text ▾'}
                          </button>
                        )}
                      </div>

                      {isSrcExpanded && src.content && (
                        <div
                          style={{
                            marginTop: '12px',
                            padding: '12px',
                            backgroundColor: 'var(--color-carbon-surface)',
                            borderRadius: '4px',
                            fontSize: '12.5px',
                            maxHeight: '260px',
                            overflowY: 'auto',
                            whiteSpace: 'pre-wrap',
                            border: '1px solid var(--color-iron-border)',
                            color: 'var(--color-cream-text)',
                          }}
                        >
                          {src.content}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </details>

            {/* Collapsible: Direct Quotation Audits (If present, Collapsed by default) */}
            {report.quote_audits && report.quote_audits.length > 0 && (
              <details className="minimal-collapse-card" style={{ marginBottom: 'var(--spacing-16)' }}>
                <summary className="minimal-collapse-summary">
                  <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span>▸</span>
                    <span>DIRECT QUOTATION AUDITS</span>
                    <span style={{ opacity: 0.6, fontSize: '11px' }}>
                      ({report.quote_audits.length} quote{report.quote_audits.length > 1 ? 's' : ''})
                    </span>
                  </span>
                  <span style={{ color: 'var(--color-zinc-mute)', fontSize: '11px' }}>
                    CLICK TO INSPECT QUOTES
                  </span>
                </summary>
                <div className="minimal-collapse-content">
                  {report.quote_audits.map((qa) => (
                    <div
                      key={qa.id}
                      style={{
                        backgroundColor: 'var(--color-void-canvas)',
                        border: '1px solid var(--color-iron-border)',
                        borderRadius: '5.6px',
                        padding: '12px 16px',
                        marginBottom: '8px',
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                        <span style={{ fontSize: '13.5px', color: 'var(--color-cream-text)' }}>
                          "{qa.quotation_text}"
                        </span>
                        <span className={`verdict-specimen-badge ${
                          qa.match_status === 'exact_match' ? 'badge-supported' : 'badge-contradicted'
                        }`}>
                          {qa.match_status.replace('_', ' ').toUpperCase()}
                        </span>
                      </div>

                      {qa.matched_source_title && (
                        <div style={{ fontSize: '12px', color: 'var(--color-mint-pulse)' }}>
                          SOURCE: {qa.matched_source_title} {qa.page_number ? `(Page ${qa.page_number})` : ''}
                        </div>
                      )}
                      {qa.source_excerpt && (
                        <div style={{ fontSize: '12.5px', color: 'var(--color-zinc-mute)', fontStyle: 'italic', marginTop: '4px' }}>
                          Matched text: "{qa.source_excerpt}"
                        </div>
                      )}
                      {qa.differences && (
                        <div style={{ fontSize: '12px', color: 'var(--color-ember-orange)', marginTop: '4px' }}>
                          Discrepancy: {qa.differences}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </details>
            )}

            {/* Categorized Factual Claims Section — Minimalist Accordion List */}
            <section style={{ marginTop: 'var(--spacing-16)' }}>
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '8px 4px 14px',
                  borderBottom: '1px solid var(--color-iron-border)',
                  marginBottom: 'var(--spacing-12)',
                  flexWrap: 'wrap',
                  gap: '8px',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <span style={{ fontFamily: 'var(--font-geist-mono)', fontSize: '12px', letterSpacing: '0.08em', color: 'var(--color-cream-text)', textTransform: 'uppercase' }}>
                    FACTUAL CLAIMS
                  </span>
                  <span style={{ fontSize: '12px', color: 'var(--color-zinc-mute)' }}>
                    ({filteredClaims.length} of {report.claims.length} claims{filterVerdict !== 'all' ? ` matching ${filterVerdict}` : ''})
                  </span>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  {filterVerdict !== 'all' && (
                    <button
                      type="button"
                      className="minimal-claim-expand-btn"
                      onClick={() => setFilterVerdict('all')}
                      style={{ color: 'var(--color-ember-orange)', borderColor: 'var(--color-ember-orange)' }}
                    >
                      Clear Filter ✕
                    </button>
                  )}
                  {filteredClaims.length > 0 && (
                    <button
                      type="button"
                      className="minimal-claim-expand-btn"
                      onClick={handleToggleExpandAll}
                      title="Expand or collapse all claims"
                    >
                      {areAllClaimsExpanded ? 'Collapse All ▴' : 'Expand All ▾'}
                    </button>
                  )}
                </div>
              </div>

              {filteredClaims.length === 0 ? (
                <div className="specimen-card" style={{ textAlign: 'center', padding: '32px' }}>
                  <p className="prose-text" style={{ color: 'var(--color-zinc-mute)' }}>
                    No claims match the active filter criteria.
                  </p>
                  <button
                    type="button"
                    className="pill-button pill-mint"
                    style={{ marginTop: '12px' }}
                    onClick={() => setFilterVerdict('all')}
                  >
                    View All Claims
                  </button>
                </div>
              ) : (
                filteredClaims.map((claim, idx) => {
                  const isExpanded = Boolean(expandedClaims[claim.id]);

                  let badgeClass = 'badge-insufficient';
                  let verdictLabel = 'INSUFFICIENT';

                  if (claim.verdict === 'supported') {
                    badgeClass = 'badge-supported';
                    verdictLabel = 'SUPPORTED';
                  } else if (claim.verdict === 'contradicted') {
                    badgeClass = 'badge-contradicted';
                    verdictLabel = 'CONTRADICTED';
                  } else if (claim.verdict === 'ambiguous') {
                    badgeClass = 'badge-ambiguous';
                    verdictLabel = 'AMBIGUOUS';
                  }

                  const claimNum = String(idx + 1).padStart(2, '0');

                  return (
                    <article key={claim.id} className="minimal-claim-item">
                      {/* Minimalist Claim Header (Click anywhere to expand/collapse) */}
                      <div
                        className="minimal-claim-header"
                        onClick={() => toggleClaimExpand(claim.id)}
                        role="button"
                        tabIndex={0}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            toggleClaimExpand(claim.id);
                          }
                        }}
                      >
                        <div className="minimal-claim-title-group">
                          <span
                            style={{
                              fontFamily: 'var(--font-geist-mono)',
                              fontSize: '11px',
                              letterSpacing: '0.06em',
                              color: 'var(--color-zinc-mute)',
                              minWidth: '24px',
                            }}
                          >
                            #{claimNum}
                          </span>

                          <div className={`verdict-specimen-badge ${badgeClass}`}>
                            {verdictLabel}
                          </div>

                          <div className="minimal-claim-text">
                            "{claim.normalized_text}"
                          </div>
                        </div>

                        <button
                          type="button"
                          className="minimal-claim-expand-btn"
                          aria-expanded={isExpanded}
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleClaimExpand(claim.id);
                          }}
                        >
                          {isExpanded ? 'Collapse ▴' : 'Details ▾'}
                        </button>
                      </div>

                      {/* Minimalist Claim Body (Only expanded when user explicitly clicks) */}
                      {isExpanded && (
                        <div className="minimal-claim-body">
                          {/* Grounded Assessment */}
                          {claim.reasoning && (
                            <div style={{ marginBottom: '14px' }}>
                              <div style={{ fontFamily: 'var(--font-geist-mono)', fontSize: '11px', color: 'var(--color-zinc-mute)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '4px' }}>
                                AUDITOR ASSESSMENT
                              </div>
                              <p style={{ margin: 0, fontSize: '13.5px', lineHeight: '1.55', color: 'var(--color-cream-text)' }}>
                                {claim.reasoning}
                              </p>
                              {claim.limitations && (
                                <p style={{ marginTop: '8px', fontSize: '12.5px', color: '#f59e0b', margin: '8px 0 0' }}>
                                  ⚠ Limitations: {claim.limitations}
                                </p>
                              )}
                            </div>
                          )}

                          {/* Cited Evidence Passages */}
                          {claim.evidence && claim.evidence.length > 0 && (
                            <div>
                              <div style={{ fontFamily: 'var(--font-geist-mono)', fontSize: '11px', color: 'var(--color-zinc-mute)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '8px' }}>
                                CITED EVIDENCE ({claim.evidence.length} PASSAGE{claim.evidence.length > 1 ? 'S' : ''})
                              </div>

                              {claim.evidence.map((ev) => (
                                <div key={ev.id} className="evidence-passage-box">
                                  <div className="evidence-source-tag">
                                    <span>📄 {ev.source_title}</span>
                                    {ev.page_number && <span>• Page {ev.page_number}</span>}
                                    {ev.relevance_score && (
                                      <span style={{ color: 'var(--color-mint-pulse)' }}>
                                        • BM25 Score: {ev.relevance_score.toFixed(2)}
                                      </span>
                                    )}
                                  </div>
                                  <div style={{ color: 'var(--color-cream-text)', fontStyle: 'italic', marginBottom: '6px', fontSize: '13px' }}>
                                    "{ev.excerpt}"
                                  </div>
                                  {ev.explanation && (
                                    <div style={{ fontSize: '12px', color: 'var(--color-zinc-mute)' }}>
                                      Correlation: {ev.explanation}
                                    </div>
                                  )}
                                </div>
                              ))}
                            </div>
                          )}

                          {(!claim.evidence || claim.evidence.length === 0) && (
                            <div style={{ fontSize: '12.5px', color: 'var(--color-zinc-mute)', fontStyle: 'italic', marginTop: '6px' }}>
                              No qualifying evidence passage was located in reference material.
                            </div>
                          )}
                        </div>
                      )}
                    </article>
                  );
                })
              )}
            </section>

            {/* Scope Disclaimer */}
            <footer style={{ textAlign: 'center', fontSize: '12px', color: 'var(--color-zinc-mute)', paddingTop: '28px', paddingBottom: '32px' }}>
              {report.scope_disclaimer}
            </footer>
          </>
        )}
      </main>
    </div>
  );
};
