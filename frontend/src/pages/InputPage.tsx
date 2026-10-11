import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiClient } from '../api/client';
import { AsciiSphere } from '../components/AsciiSphere';
import type {
  HealthResponse,
  SourceType,
} from '../types/api';

const SAMPLE_AI_REPLY = `The James Webb Space Telescope (JWST) was launched on December 25, 2021, aboard an Ariane 5 rocket from Kourou, French Guiana. JWST operates in an orbit around the Sun-Earth Lagrange point L2, approximately 1.5 million kilometers from Earth. Its primary mirror consists of 18 hexagonal segments made of gold-plated beryllium, spanning 6.5 meters in diameter. However, JWST was launched in 2018 and features an 11-meter diameter mirror.`;

const SAMPLE_REFERENCE = `The James Webb Space Telescope (JWST) is a space telescope designed primarily to conduct infrared astronomy. It was launched on 25 December 2021 on an Ariane 5 rocket from Kourou, French Guiana, and arrived at the Sun-Earth L2 Lagrange point in January 2022, approximately 1.5 million kilometers (930,000 mi) from Earth. The telescope's primary mirror consists of 18 hexagonal mirror segments made of gold-plated beryllium, which together create a 6.5-meter (21 ft) diameter mirror.`;

export const InputPage: React.FC = () => {
  const navigate = useNavigate();

  // Health state
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [healthLoading, setHealthLoading] = useState<boolean>(true);

  // Form inputs
  const [answer, setAnswer] = useState<string>('');
  const [sourceTitle, setSourceTitle] = useState<string>('Primary Reference Documentation');
  const [sourceType, setSourceType] = useState<SourceType>('text');
  const [sourceContent, setSourceContent] = useState<string>('');
  const [pdfFile, setPdfFile] = useState<File | null>(null);

  // Automated Execution Pipeline states
  const [isProcessing, setIsProcessing] = useState<boolean>(false);
  const [currentStep, setCurrentStep] = useState<number>(0);
  const [stepDetail, setStepDetail] = useState<string>('');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);

  // Refs for keyboard shortcuts
  const formRef = useRef<HTMLFormElement>(null);

  useEffect(() => {
    let isMounted = true;
    apiClient
      .checkHealth()
      .then((data) => {
        if (isMounted) {
          setHealth(data);
          setHealthError(null);
          setHealthLoading(false);
        }
      })
      .catch((err: Error) => {
        if (isMounted) {
          setHealthError(err.message);
          setHealthLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, []);

  const handleLoadSample = () => {
    setAnswer(SAMPLE_AI_REPLY);
    setSourceTitle('NASA / ESA JWST Mission Profile');
    setSourceType('text');
    setSourceContent(SAMPLE_REFERENCE);
    setValidationError(null);
    setErrorMessage(null);
  };

  const handleReset = () => {
    setAnswer('');
    setSourceTitle('Primary Reference Documentation');
    setSourceContent('');
    setPdfFile(null);
    setValidationError(null);
    setErrorMessage(null);
    setIsProcessing(false);
    setCurrentStep(0);
  };

  /**
   * Automated verification pipeline execution:
   * 1. Register run & ingest sources
   * 2. Extract atomic claims via Gemini
   * 3. Retrieve BM25 candidate evidence passages
   * 4. Categorize claims (Supported, Contradicted, etc.) and audit quotes
   */
  const executeVerification = async () => {
    setErrorMessage(null);
    setValidationError(null);

    const trimmedAnswer = answer.trim();
    if (!trimmedAnswer || trimmedAnswer.length < 5) {
      setValidationError('AI reply must contain at least 5 characters.');
      return;
    }

    const trimmedTitle = sourceTitle.trim() || (pdfFile ? pdfFile.name : 'Primary Reference');

    if (sourceType === 'text') {
      const trimmedContent = sourceContent.trim();
      if (!trimmedContent) {
        setValidationError('Please paste your reference source text.');
        return;
      }
    } else if (sourceType === 'pdf') {
      if (!pdfFile) {
        setValidationError('Please select a PDF reference document to upload.');
        return;
      }
      if (!pdfFile.name.toLowerCase().endsWith('.pdf')) {
        setValidationError('The selected file must have a .pdf extension.');
        return;
      }
      if (pdfFile.size > 10 * 1024 * 1024) {
        setValidationError('PDF file size exceeds maximum limit of 10 MB.');
        return;
      }
    }

    setIsProcessing(true);
    setCurrentStep(1);
    setStepDetail('Fingerprinting reference source and registering run...');

    try {
      // Step 1: Create Run & Ingest Source
      let runId = '';
      if (sourceType === 'pdf' && pdfFile) {
        const response = await apiClient.createRunWithPdf(trimmedAnswer, pdfFile, trimmedTitle);
        runId = response.run_id;
      } else {
        const response = await apiClient.createRun({
          answer: trimmedAnswer,
          sources: [
            {
              title: trimmedTitle,
              source_type: 'text',
              content: sourceContent,
            },
          ],
        });
        runId = response.run_id;
      }

      // Step 2: Extract Claims
      setCurrentStep(2);
      setStepDetail('Decomposing AI answer into atomic verifiable claims via Gemini...');
      await apiClient.extractClaims(runId);

      // Step 3: Retrieve Evidence
      setCurrentStep(3);
      setStepDetail('Searching candidate evidence passages across reference sources via BM25...');
      await apiClient.retrieveEvidence(runId);

      // Step 4: Categorize Claims & Audit Quotes
      setCurrentStep(4);
      setStepDetail('Auditing claims strictly against retrieved source evidence...');
      await apiClient.assessClaims(runId);

      setCurrentStep(5);
      setStepDetail('Audit completed. Displaying categorized factual specimen report.');
      setIsProcessing(false);

      // Navigate to dedicated report URL so it is bookmarkable
      navigate(`/report/${runId}`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Verification pipeline encountered an error.';
      setErrorMessage(msg);
      setIsProcessing(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    // If Enter is pressed with Ctrl/Cmd or outside multiline input
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      executeVerification();
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    executeVerification();
  };

  return (
    <div>
      {/* Sticky Top Navigation Bar */}
      <nav className="navbar">
        <div className="nav-container">
          <div className="nav-brand">
            <div className="nav-logo-glyph">◈</div>
            <span className="nav-brand-title">SECOND OPINION</span>
            <div className="nav-status-indicator">
              <span className={`status-beacon ${healthError ? 'offline' : ''}`} />
              <span>{healthLoading ? 'CONNECTING...' : health ? 'ONLINE' : 'OFFLINE'}</span>
            </div>
          </div>

          <div className="nav-actions">
            <button
              type="button"
              className="pill-button pill-amber"
              onClick={handleLoadSample}
              disabled={isProcessing}
              title="Load real-world sample to test verification instantly"
            >
              ✦ Load Example
            </button>
            <button
              type="button"
              className="pill-button pill-red"
              onClick={handleReset}
              disabled={isProcessing}
              title="Clear all fields"
            >
              ✕ Reset
            </button>
            <button
              type="button"
              className="pill-button pill-green"
              onClick={executeVerification}
              disabled={isProcessing}
              title="Audit AI Answer strictly against sources"
            >
              {isProcessing ? 'Verifying...' : '↵ Audit [Enter]'}
            </button>
          </div>
        </div>
      </nav>

      {/* Main Container */}
      <main className="page-column" onKeyDown={handleKeyDown}>
        {/* Full-Viewport Midjourney Hero with Generative ASCII Sphere */}
        <section className="hero-visual-section">
          <AsciiSphere active={isProcessing} />
          <div className="hero-content">
            <h1 className="hero-title">Second Opinion</h1>
            <p className="hero-subtitle prose-text">
              Deep-ocean factual verification terminal. Evaluates AI answers strictly
              against user-supplied reference sources. Pretrained model knowledge is excluded.
            </p>
            <div className="hero-instruction-tag">
              <span>Minimal input: Paste AI reply + Reference source ➔ Press <kbd>Enter ↵</kbd></span>
            </div>
          </div>
        </section>

        {/* Validation & Error Banners */}
        {validationError && (
          <div className="specimen-alert specimen-alert-warning" role="alert">
            <span>⚠</span>
            <div>
              <strong>Input Incomplete:</strong> {validationError}
            </div>
          </div>
        )}

        {errorMessage && (
          <div className="specimen-alert specimen-alert-danger" role="alert">
            <span>▲</span>
            <div>
              <strong>Verification Error:</strong> {errorMessage}
            </div>
          </div>
        )}

        {/* Real-Time Telemetry Pipeline Display (Visible when running) */}
        {isProcessing && (
          <section className="telemetry-stream-card">
            <div className="telemetry-header">
              <span className="telemetry-terminal-title">
                <span className="spinner-glyph">⚙</span> VERIFICATION TELEMETRY STREAM
              </span>
              <span style={{ fontSize: '12px', color: 'var(--color-mist)' }}>
                {stepDetail}
              </span>
            </div>

            <div className="telemetry-step-list">
              <div className="telemetry-step-item">
                <div className={`step-indicator ${currentStep > 1 ? 'done' : currentStep === 1 ? 'active' : 'pending'}`}>
                  {currentStep > 1 ? '✓' : '1'}
                </div>
                <div>
                  <div className="step-text-title">Reference Ingestion & SHA-256 Fingerprinting</div>
                  <div className="step-text-sub">Persisting immutable ground-truth document records</div>
                </div>
              </div>

              <div className="telemetry-step-item">
                <div className={`step-indicator ${currentStep > 2 ? 'done' : currentStep === 2 ? 'active' : 'pending'}`}>
                  {currentStep > 2 ? '✓' : '2'}
                </div>
                <div>
                  <div className="step-text-title">Atomic Factual Claim Extraction</div>
                  <div className="step-text-sub">Decomposing AI answer into isolated verifiable statements</div>
                </div>
              </div>

              <div className="telemetry-step-item">
                <div className={`step-indicator ${currentStep > 3 ? 'done' : currentStep === 3 ? 'active' : 'pending'}`}>
                  {currentStep > 3 ? '✓' : '3'}
                </div>
                <div>
                  <div className="step-text-title">Lexical Passage Evidence Retrieval</div>
                  <div className="step-text-sub">Scoring and extracting candidate citations via BM25 ranking</div>
                </div>
              </div>

              <div className="telemetry-step-item">
                <div className={`step-indicator ${currentStep > 4 ? 'done' : currentStep === 4 ? 'active' : 'pending'}`}>
                  {currentStep > 4 ? '✓' : '4'}
                </div>
                <div>
                  <div className="step-text-title">Grounded Assessment & Categorization</div>
                  <div className="step-text-sub">
                    Classifying claims into Supported, Contradicted, Insufficient, or Ambiguous
                  </div>
                </div>
              </div>
            </div>
          </section>
        )}

        {/* Main Verification Input Form */}
        <form ref={formRef} onSubmit={handleSubmit}>
          {/* Section 1: AI-Generated Answer */}
          <section className="specimen-card" style={{ marginBottom: 'var(--spacing-32)' }}>
            <div className="card-header-bar">
              <label htmlFor="ai-answer-textarea" className="card-label">
                <span className="heading-glyph">⚙</span> 1. AI Reply to Audit
              </label>
              <span className="card-metadata">{answer.length} chars</span>
            </div>
            <p className="prose-text" style={{ fontSize: '14px', color: 'var(--color-mist)', marginBottom: 'var(--spacing-16)' }}>
              Paste the text from ChatGPT, Claude, Gemini, or any LLM model that requires factual auditing.
            </p>
            <textarea
              id="ai-answer-textarea"
              className="terminal-textarea"
              rows={6}
              disabled={isProcessing}
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              placeholder="e.g. The James Webb Space Telescope was launched on December 25, 2021... (Press Enter or Ctrl+Enter to audit)"
            />
          </section>

          {/* Section 2: User Reference Source */}
          <section className="specimen-card" style={{ marginBottom: 'var(--spacing-32)' }}>
            <div className="card-header-bar">
              <label className="card-label">
                <span className="heading-glyph">ℹ</span> 2. Ground-Truth Reference Source
              </label>
              <span className="card-metadata">Source-Scoped Only</span>
            </div>
            <p className="prose-text" style={{ fontSize: '14px', color: 'var(--color-mist)', marginBottom: 'var(--spacing-16)' }}>
              Provide the reference documentation, manual, or report text. Factual claims are evaluated strictly against this source.
            </p>

            {/* Source Mode Switcher */}
            <div className="source-tab-tray">
              <button
                type="button"
                className={`source-tab-btn ${sourceType === 'text' ? 'active' : ''}`}
                onClick={() => setSourceType('text')}
                disabled={isProcessing}
              >
                Pasted Reference Text
              </button>
              <button
                type="button"
                className={`source-tab-btn ${sourceType === 'pdf' ? 'active' : ''}`}
                onClick={() => setSourceType('pdf')}
                disabled={isProcessing}
              >
                Upload PDF Document
              </button>
            </div>

            {/* Source Title Input */}
            <div style={{ marginBottom: 'var(--spacing-16)' }}>
              <label htmlFor="source-title-input" style={{ fontSize: '13px', color: 'var(--color-mist)', display: 'block', marginBottom: '6px' }}>
                Source Identifier / Title (Optional):
              </label>
              <input
                id="source-title-input"
                type="text"
                className="terminal-input-single"
                disabled={isProcessing}
                value={sourceTitle}
                onChange={(e) => setSourceTitle(e.target.value)}
                placeholder="e.g. Official Mission Specifications"
              />
            </div>

            {/* Text Source Input */}
            {sourceType === 'text' && (
              <div>
                <textarea
                  id="source-content-textarea"
                  className="terminal-textarea"
                  rows={8}
                  disabled={isProcessing}
                  value={sourceContent}
                  onChange={(e) => setSourceContent(e.target.value)}
                  placeholder="Paste reliable reference documentation, article text, or ground-truth excerpt here..."
                />
              </div>
            )}

            {/* PDF Upload Zone */}
            {sourceType === 'pdf' && (
              <div>
                <label htmlFor="source-pdf-file-input">
                  <div className="dropzone-container">
                    <input
                      id="source-pdf-file-input"
                      type="file"
                      accept=".pdf,application/pdf"
                      disabled={isProcessing}
                      style={{ display: 'none' }}
                      onChange={(e) => {
                        const file = e.target.files?.[0] || null;
                        setPdfFile(file);
                        if (file && (!sourceTitle || sourceTitle === 'Primary Reference Documentation')) {
                          setSourceTitle(file.name);
                        }
                      }}
                    />
                    <div style={{ color: 'var(--color-ghost-white)', fontSize: '15px', marginBottom: '6px' }}>
                      {pdfFile ? `Selected: ${pdfFile.name}` : 'Click to select PDF document'}
                    </div>
                    <div style={{ fontSize: '13px', color: 'var(--color-mist)' }}>
                      {pdfFile
                        ? `${(pdfFile.size / (1024 * 1024)).toFixed(2)} MB • Text pages will be parsed automatically`
                        : 'Supports PDF up to 10 MB, up to 100 pages'}
                    </div>
                  </div>
                </label>
              </div>
            )}
          </section>

          {/* Action Dispatch Bar */}
          <div className="action-dispatch-bar">
            <div className="dispatch-hint">
              <span>Audit shortcut:</span>
              <kbd>Enter ↵</kbd>
              <span>or</span>
              <kbd>Ctrl+Enter</kbd>
            </div>

            <button
              type="submit"
              className="pill-button pill-green"
              disabled={isProcessing}
              style={{ padding: '10px 28px', fontSize: '15px' }}
            >
              {isProcessing ? 'Auditing Factual Claims...' : '↵ Audit Answer & Categorize Claims'}
            </button>
          </div>
        </form>

        {/* Categorized Verdict Taxonomy Specimen Tray */}
        <section className="specimen-card">
          <div className="section-heading" style={{ fontSize: '20px', marginBottom: 'var(--spacing-16)' }}>
            <span className="heading-glyph">✦</span> Categorization Taxonomy
          </div>
          <p className="prose-text" style={{ fontSize: '14px', color: 'var(--color-mist)', marginBottom: 'var(--spacing-24)' }}>
            Claims are audited strictly against supplied sources without relying on pretrained web training data:
          </p>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 'var(--spacing-16)' }}>
            <div style={{ background: 'var(--color-cosmic-void)', padding: '16px', borderRadius: '8px', border: '1px solid rgba(229, 231, 235, 0.08)' }}>
              <div className="verdict-specimen-badge badge-supported" style={{ marginBottom: '8px' }}>
                Supported / Correct
              </div>
              <p style={{ fontSize: '13px', color: 'var(--color-mist)', margin: 0 }}>
                Directly substantiated by verified text passages in the supplied reference documents.
              </p>
            </div>

            <div style={{ background: 'var(--color-cosmic-void)', padding: '16px', borderRadius: '8px', border: '1px solid rgba(229, 231, 235, 0.08)' }}>
              <div className="verdict-specimen-badge badge-contradicted" style={{ marginBottom: '8px' }}>
                Contradicted
              </div>
              <p style={{ fontSize: '13px', color: 'var(--color-mist)', margin: 0 }}>
                Directly refuted or conflicted by factual statements in the supplied reference documents.
              </p>
            </div>

            <div style={{ background: 'var(--color-cosmic-void)', padding: '16px', borderRadius: '8px', border: '1px solid rgba(229, 231, 235, 0.08)' }}>
              <div className="verdict-specimen-badge badge-insufficient" style={{ marginBottom: '8px' }}>
                Insufficient Evidence
              </div>
              <p style={{ fontSize: '13px', color: 'var(--color-mist)', margin: 0 }}>
                Reference documents lack relevant facts to confirm or deny. Never presumed false.
              </p>
            </div>

            <div style={{ background: 'var(--color-cosmic-void)', padding: '16px', borderRadius: '8px', border: '1px solid rgba(229, 231, 235, 0.08)' }}>
              <div className="verdict-specimen-badge badge-ambiguous" style={{ marginBottom: '8px' }}>
                Ambiguous
              </div>
              <p style={{ fontSize: '13px', color: 'var(--color-mist)', margin: 0 }}>
                Evidence or statement wording supports multiple materially distinct interpretations.
              </p>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
};
