import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiClient } from '../api/client';
import { SpectrogramWaveform } from '../components/SpectrogramWaveform';
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
  const [sourceType, setSourceType] = useState<SourceType>('ai_crosscheck');
  const [sourceContent, setSourceContent] = useState<string>('');
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [prefilledFromExtension, setPrefilledFromExtension] = useState<boolean>(false);

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

    // Check for pre-filled text from Chrome Extension via URL hash or query params
    try {
      let candidateText: string | null = null;
      if (window.location.hash.startsWith('#audit=')) {
        candidateText = decodeURIComponent(window.location.hash.substring(7));
      } else {
        const urlParams = new URLSearchParams(window.location.search);
        const auditQuery = urlParams.get('audit');
        if (auditQuery) {
          candidateText = auditQuery;
        }
      }

      if (candidateText && candidateText.trim().length > 0) {
        setAnswer(candidateText.trim());
        setSourceType('ai_crosscheck');
        setSourceTitle('Autonomous AI Cross-Check Dossier');
        setPrefilledFromExtension(true);
        // Clear hash so page reload doesn't trigger unexpected state
        window.history.replaceState(null, '', window.location.pathname);
      }
    } catch {
      // Ignore URL parsing errors
    }

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
    setPrefilledFromExtension(false);
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
    setPrefilledFromExtension(false);
  };

  /**
   * Automated verification pipeline execution:
   * 1. Register run & ingest sources (or generate autonomous crosscheck)
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
        setValidationError('Please paste your reference source text, or switch to AI Cross-Check.');
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
    setStepDetail(
      sourceType === 'ai_crosscheck'
        ? 'Compiling autonomous factual cross-check dossier and registering run...'
        : 'Fingerprinting reference source and registering run...'
    );

    try {
      // Step 1: Create Run & Ingest Source
      let runId = '';
      if (sourceType === 'pdf' && pdfFile) {
        const response = await apiClient.createRunWithPdf(trimmedAnswer, pdfFile, trimmedTitle);
        runId = response.run_id;
      } else if (sourceType === 'ai_crosscheck') {
        const response = await apiClient.createRun({
          answer: trimmedAnswer,
          sources: [
            {
              title: trimmedTitle || 'Autonomous AI Cross-Check Dossier',
              source_type: 'ai_crosscheck',
              content: '',
            },
          ],
        });
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
      {/* Top Navigation Bar (Vapi Specification: Transparent, 1px Iron divider, tracked mono links) */}
      <nav className="navbar">
        <div className="nav-container">
          <div className="nav-brand">
            <div className="nav-logo-glyph">◈</div>
            <span className="nav-brand-title">SECOND OPINION</span>
            <div className="nav-status-indicator">
              <span className={`status-beacon ${healthError ? 'offline' : ''}`} />
              <span>{healthLoading ? 'CONNECTING' : health ? 'SYSTEM READY' : 'OFFLINE'}</span>
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
              className="pill-button pill-ember"
              onClick={executeVerification}
              disabled={isProcessing}
              title="Audit AI Answer strictly against sources"
            >
              {isProcessing ? 'Verifying...' : 'Audit Answer →'}
            </button>
          </div>
        </div>
      </nav>

      {/* Main Container - Desktop-First Vapi Workspace */}
      <main className="page-column desktop-wide" onKeyDown={handleKeyDown}>
        {/* Vapi Hero Section: Headline at weight 300, subtext, and Spectrogram Waveform Graphic */}
        <section className="hero-vapi-section">
          <h1 className="hero-headline">
            Fact-checking console for generative AI
          </h1>
          <p className="hero-subtext">
            Decomposes model answers into atomic factual claims and verifies them strictly against source evidence or autonomous cross-examination.
          </p>

          {/* Interactive Console Callout Pill */}
          <button
            type="button"
            className="vapi-console-pill"
            onClick={executeVerification}
            disabled={isProcessing}
          >
            <span>{isProcessing ? 'RUNNING VERIFICATION PIPELINE' : 'INITIATE AUDIT CONSOLE'}</span>
            <div className="vapi-console-dots">
              <span />
              <span />
              <span />
              <span />
            </div>
          </button>

          {/* 6-Color Spectrogram Waveform Graphic (Vapi signature element) */}
          <SpectrogramWaveform active={isProcessing} />
        </section>

        {/* Validation & Error Banners */}
        {validationError && (
          <div className="specimen-alert specimen-alert-warning" role="alert">
            <span>⚠</span>
            <div>
              <strong>INPUT REQUIRED:</strong> {validationError}
            </div>
          </div>
        )}

        {errorMessage && (
          <div className="specimen-alert specimen-alert-danger" role="alert">
            <span>▲</span>
            <div>
              <strong>SYSTEM FAULT:</strong> {errorMessage}
            </div>
          </div>
        )}

        {/* Main Desktop-First Side-by-Side Form */}
        <form ref={formRef} onSubmit={handleSubmit}>
          {/* Extension Notification Banner */}
          {prefilledFromExtension && (
            <div className="extension-prefill-banner">
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span className="prefill-tag">CHROME EXTENSION</span>
                <span>Response imported from ChatGPT. Autonomous AI cross-check mode selected.</span>
              </div>
              <button
                type="button"
                className="pill-button"
                style={{ padding: '4px 12px', fontSize: '11px' }}
                onClick={() => setPrefilledFromExtension(false)}
              >
                Dismiss
              </button>
            </div>
          )}

          <div className="workspace-split-grid">
            {/* Left Panel: AI-Generated Answer */}
            <div className="workspace-card">
              <div className="card-header-bar">
                <label htmlFor="ai-answer-textarea" className="card-label">
                  1. AI REPLY TO AUDIT
                </label>
                <span className="card-metadata">{answer.length} CHARS</span>
              </div>
              <p className="prose-text" style={{ fontSize: '13px', marginBottom: 'var(--spacing-16)' }}>
                Paste the response from ChatGPT, Claude, Gemini, or any LLM model that requires factual validation.
              </p>
              <div className="workspace-card-body">
                <textarea
                  id="ai-answer-textarea"
                  className="workspace-textarea"
                  disabled={isProcessing}
                  value={answer}
                  onChange={(e) => setAnswer(e.target.value)}
                  placeholder="Paste AI answer text here... (Ctrl+Enter to initiate audit)"
                />
              </div>
            </div>

            {/* Right Panel: Ground-Truth Reference Source */}
            <div className="workspace-card">
              <div className="card-header-bar">
                <label className="card-label">
                  2. GROUND-TRUTH REFERENCE MODE
                </label>
                <span className="card-metadata">
                  {sourceType === 'ai_crosscheck'
                    ? 'AUTONOMOUS'
                    : sourceType === 'pdf'
                    ? 'PDF DOCUMENT'
                    : 'PASTED TEXT'}
                </span>
              </div>
              <p className="prose-text" style={{ fontSize: '13px', marginBottom: 'var(--spacing-16)' }}>
                Select autonomous AI cross-check (no upload needed), paste reference text, or upload a PDF document.
              </p>

              {/* 3-Way Source Mode Switcher */}
              <div className="source-tab-tray">
                <button
                  type="button"
                  className={`source-tab-btn crosscheck-btn ${sourceType === 'ai_crosscheck' ? 'active' : ''}`}
                  onClick={() => setSourceType('ai_crosscheck')}
                  disabled={isProcessing}
                >
                  ✦ AI Cross-Check
                </button>
                <button
                  type="button"
                  className={`source-tab-btn ${sourceType === 'text' ? 'active' : ''}`}
                  onClick={() => setSourceType('text')}
                  disabled={isProcessing}
                >
                  Pasted Text
                </button>
                <button
                  type="button"
                  className={`source-tab-btn ${sourceType === 'pdf' ? 'active' : ''}`}
                  onClick={() => setSourceType('pdf')}
                  disabled={isProcessing}
                >
                  Upload PDF
                </button>
              </div>

              <div className="workspace-card-body">
                {/* Mode 1: AI Autonomous Cross-Check */}
                {sourceType === 'ai_crosscheck' && (
                  <div className="ai-crosscheck-panel">
                    <div className="crosscheck-badge">
                      <span>◈</span> AUTONOMOUS CROSS-CHECK
                    </div>
                    <h3 style={{ color: 'var(--color-cream-text)', fontSize: '16px', fontWeight: 500, marginBottom: '6px' }}>
                      Zero-Upload Factual Verification
                    </h3>
                    <p style={{ fontSize: '13px', color: 'var(--color-zinc-mute)', maxWidth: '420px', lineHeight: 1.5 }}>
                      The engine compiles an objective factual reference dossier and audits each proposition against authoritative consensus without requiring external manual files.
                    </p>
                    <div className="crosscheck-feature-list">
                      <div className="crosscheck-feature-item">
                        <span className="glyph">✓</span>
                        <span>Zero manual document upload or reference pasting required</span>
                      </div>
                      <div className="crosscheck-feature-item">
                        <span className="glyph">✓</span>
                        <span>Isolates and validates discrete numerical and entity claims</span>
                      </div>
                      <div className="crosscheck-feature-item">
                        <span className="glyph">✓</span>
                        <span>Classifies output into Supported, Contradicted, or Ambiguous</span>
                      </div>
                    </div>
                  </div>
                )}

                {/* Mode 2: Pasted Text */}
                {sourceType === 'text' && (
                  <div style={{ display: 'flex', flexDirection: 'column', flex: 1 }}>
                    <div style={{ marginBottom: 'var(--spacing-12)' }}>
                      <label htmlFor="source-title-input" style={{ fontSize: '11px', color: 'var(--color-zinc-mute)', display: 'block', marginBottom: '4px' }}>
                        SOURCE IDENTIFIER / TITLE (OPTIONAL):
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
                    <textarea
                      id="source-content-textarea"
                      className="workspace-textarea"
                      disabled={isProcessing}
                      value={sourceContent}
                      onChange={(e) => setSourceContent(e.target.value)}
                      placeholder="Paste reliable reference documentation or ground-truth excerpt here..."
                    />
                  </div>
                )}

                {/* Mode 3: PDF Document */}
                {sourceType === 'pdf' && (
                  <div style={{ display: 'flex', flexDirection: 'column', flex: 1 }}>
                    <div style={{ marginBottom: 'var(--spacing-12)' }}>
                      <label htmlFor="source-title-input-pdf" style={{ fontSize: '11px', color: 'var(--color-zinc-mute)', display: 'block', marginBottom: '4px' }}>
                        DOCUMENT TITLE (OPTIONAL):
                      </label>
                      <input
                        id="source-title-input-pdf"
                        type="text"
                        className="terminal-input-single"
                        disabled={isProcessing}
                        value={sourceTitle}
                        onChange={(e) => setSourceTitle(e.target.value)}
                        placeholder="e.g. Technical Research Paper.pdf"
                      />
                    </div>
                    <label htmlFor="source-pdf-file-input" style={{ flex: 1, display: 'flex', cursor: 'pointer' }}>
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
                        <div style={{ color: 'var(--color-cream-text)', fontSize: '14px', marginBottom: '6px', fontWeight: 500 }}>
                          {pdfFile ? `Selected: ${pdfFile.name}` : 'Click to select PDF document'}
                        </div>
                        <div style={{ fontSize: '12px', color: 'var(--color-zinc-mute)' }}>
                          {pdfFile
                            ? `${(pdfFile.size / (1024 * 1024)).toFixed(2)} MB • Text extracted automatically`
                            : 'Supports PDF documents up to 10 MB, up to 100 pages'}
                        </div>
                      </div>
                    </label>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Real-Time Telemetry Pipeline Display (Positioned below the two columns) */}
          {isProcessing && (
            <section className="telemetry-stream-card" style={{ marginTop: 'var(--spacing-20)', marginBottom: 'var(--spacing-16)' }}>
              <div className="telemetry-header">
                <span className="telemetry-terminal-title">
                  ⚙ PIPELINE TELEMETRY STREAM
                </span>
                <span style={{ fontFamily: 'var(--font-geist-mono)', fontSize: '12px', color: 'var(--color-zinc-mute)' }}>
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

          {/* Action Dispatch Bar: Vapi Ember + Mint CTA Binary Pair */}
          <div className="action-dispatch-bar">
            <div className="dispatch-hint">
              <span>KEYBOARD SHORTCUT:</span>
              <kbd>Ctrl+Enter</kbd>
              <span>OR</span>
              <kbd>Enter ↵</kbd>
            </div>

            <div style={{ display: 'flex', gap: 'var(--spacing-12)' }}>
              <button
                type="button"
                className="pill-button pill-mint"
                onClick={handleLoadSample}
                disabled={isProcessing}
              >
                Sample Data
              </button>

              <button
                type="submit"
                className="pill-button pill-ember"
                disabled={isProcessing}
                style={{ padding: '10px 24px' }}
              >
                {isProcessing ? 'Verifying Answers...' : 'Request Audit →'}
              </button>
            </div>
          </div>
        </form>

        {/* Categorized Verdict Taxonomy Specimen Tray (5.6px sharp cards, Iron Border hairlines) */}
        <section className="specimen-card" style={{ marginTop: 'var(--spacing-16)' }}>
          <div className="card-header-bar">
            <span className="card-label">CATEGORIZATION TAXONOMY</span>
            <span className="card-metadata">RIGOROUS EVIDENCE MAPPING</span>
          </div>
          <p className="prose-text" style={{ fontSize: '13.5px', marginBottom: 'var(--spacing-20)' }}>
            Every atomic claim extracted from the AI reply is categorized into four mutually exclusive operational verdicts:
          </p>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 'var(--spacing-16)' }}>
            <div style={{ background: 'var(--color-void-canvas)', padding: '16px', borderRadius: '5.6px', border: '1px solid var(--color-iron-border)' }}>
              <div className="verdict-specimen-badge badge-supported" style={{ marginBottom: '8px' }}>
                SUPPORTED
              </div>
              <p style={{ fontSize: '13px', color: 'var(--color-zinc-mute)', margin: 0 }}>
                Directly corroborated by verified passages in the reference record.
              </p>
            </div>

            <div style={{ background: 'var(--color-void-canvas)', padding: '16px', borderRadius: '5.6px', border: '1px solid var(--color-iron-border)' }}>
              <div className="verdict-specimen-badge badge-contradicted" style={{ marginBottom: '8px' }}>
                CONTRADICTED
              </div>
              <p style={{ fontSize: '13px', color: 'var(--color-zinc-mute)', margin: 0 }}>
                Directly refuted or conflicted by verified factual statements.
              </p>
            </div>

            <div style={{ background: 'var(--color-void-canvas)', padding: '16px', borderRadius: '5.6px', border: '1px solid var(--color-iron-border)' }}>
              <div className="verdict-specimen-badge badge-insufficient" style={{ marginBottom: '8px' }}>
                INSUFFICIENT
              </div>
              <p style={{ fontSize: '13px', color: 'var(--color-zinc-mute)', margin: 0 }}>
                Reference records lack conclusive facts to confirm or deny. Never presumed false.
              </p>
            </div>

            <div style={{ background: 'var(--color-void-canvas)', padding: '16px', borderRadius: '5.6px', border: '1px solid var(--color-iron-border)' }}>
              <div className="verdict-specimen-badge badge-ambiguous" style={{ marginBottom: '8px' }}>
                AMBIGUOUS
              </div>
              <p style={{ fontSize: '13px', color: 'var(--color-zinc-mute)', margin: 0 }}>
                Evidence or statement wording supports multiple materially distinct interpretations.
              </p>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
};
