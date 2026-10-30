import React, { useEffect, useState } from 'react';
import type { AnalysisResponse, Habit, SampleItem } from './types';
import { ApiError, analyzeSample, analyzeUpload, fetchSamples } from './services/api';
import { SampleDataSelector } from './components/SampleDataSelector';
import { UploadDropzone } from './components/UploadDropzone';
import { Headline } from './components/Headline';
import { HabitCard } from './components/HabitCard';
import { TradeEvidenceModal } from './components/TradeEvidenceModal';
import { WarningsBanner } from './components/WarningsBanner';
import { DisclaimerFooter } from './components/DisclaimerFooter';

export const App: React.FC = () => {
  const [samples, setSamples] = useState<SampleItem[]>([]);
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [showColdStartWarning, setShowColdStartWarning] = useState<boolean>(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [selectedHabitForEvidence, setSelectedHabitForEvidence] = useState<Habit | null>(null);

  // Load sample catalogue on initial mount
  useEffect(() => {
    fetchSamples()
      .then((data) => setSamples(data))
      .catch((err: unknown) => {
        // Non-blocking error for samples list
        console.warn('Failed to load sample catalogue:', err);
      });
  }, []);

  // 5-second cold-start timeout warning
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    if (loading) {

      setShowColdStartWarning(false);
      timer = setTimeout(() => {
        setShowColdStartWarning(true);
      }, 5000);
    } else {
      setShowColdStartWarning(false);
    }
    return () => clearTimeout(timer);
  }, [loading]);

  const handleRunSample = async (sampleName: string) => {
    setLoading(true);
    setError(null);
    try {
      const result = await analyzeSample(sampleName);
      setAnalysis(result);
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setError(err);
      } else {
        setError(new ApiError(0, 'An unexpected error occurred. Please try again.'));
      }
    } finally {
      setLoading(false);
    }
  };

  const handleUploadFile = async (file: File) => {
    setLoading(true);
    setError(null);
    try {
      const result = await analyzeUpload(file);
      setAnalysis(result);
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setError(err);
      } else {
        setError(new ApiError(0, 'An unexpected error occurred while analyzing upload.'));
      }
    } finally {
      setLoading(false);
    }
  };

  const handleStartOver = () => {
    setAnalysis(null);
    setError(null);
    setSelectedHabitForEvidence(null);
  };

  return (
    <div className="app-container">
      <header className="app-header">
        <h1 className="brand-title">TradeMirror</h1>
        {analysis && (
          <button
            type="button"
            className="start-over-btn"
            onClick={handleStartOver}
            aria-label="Start over with another file or sample"
          >
            Start over
          </button>
        )}
      </header>

      {/* Accessible live region for screen readers */}
      <div className="visually-hidden" aria-live="polite" style={{ display: 'none' }}>
        {loading
          ? 'Analyzing trading data, please wait.'
          : error
            ? `Analysis error: ${error.message}`
            : analysis
              ? 'Analysis complete. Results displayed.'
              : 'Ready for analysis.'}
      </div>

      <main>
        {/* Error State */}
        {error && (
          <div className="error-panel" data-testid="error-panel" role="alert">
            <h2 className="error-title">Unable to complete analysis</h2>
            <p className="error-message">{error.message}</p>
            {error.requestId && (
              <span className="request-id-tag">Request ID: {error.requestId}</span>
            )}
            <button
              type="button"
              className="primary-btn"
              onClick={handleStartOver}
              style={{ marginTop: '0.5rem' }}
            >
              Try again
            </button>
          </div>
        )}

        {/* Loading State with Skeletons */}
        {loading && (
          <div className="loading-box" data-testid="loading-box">
            {showColdStartWarning && (
              <div className="cold-start-banner" role="status">
                Waking up the server. The first request after a quiet period can take up to a minute.
              </div>
            )}

            <div className="skeleton-card">
              <div className="skeleton-line short" />
              <div className="skeleton-line long" />
              <div className="skeleton-line medium" />
            </div>

            <div className="skeleton-card">
              <div className="skeleton-line short" />
              <div className="skeleton-line long" />
              <div className="skeleton-line medium" />
            </div>
          </div>
        )}

        {/* Landing Screen */}
        {!loading && !analysis && !error && (
          <div className="landing-section">
            <div className="hero-box">
              <h2 className="hero-title">
                Find the two or three habits costing you the most money, from a month of your own orders.
              </h2>
              <p className="hero-subtitle">
                Deterministic post-trade review for retail Indian Futures &amp; Options traders.
              </p>
            </div>

            <SampleDataSelector
              samples={samples}
              onSelectSample={handleRunSample}
              isLoading={loading}
            />

            <UploadDropzone onFileSelect={handleUploadFile} isLoading={loading} />

            <p className="privacy-banner">Your file is analysed in memory and is not stored.</p>
          </div>
        )}

        {/* Results Screen */}
        {!loading && analysis && !error && (
          <div className="results-section">
            <WarningsBanner
              warningsTotal={analysis.warnings_total}
              warnings={analysis.warnings}
              counts={analysis.dataset.counts}
            />

            {analysis.material ? (
              <>
                <Headline
                  nHabits={analysis.habits.length}
                  context={analysis.context}
                  dataset={analysis.dataset}
                />

                <div className="source-chip-box">
                  <span
                    className="source-badge"
                    title={
                      analysis.narrative.source === 'llm' && analysis.verification.passed
                        ? 'Generated by LLM and passed deterministic grounding verification against computed numbers.'
                        : 'Generated from standard deterministic narrative templates.'
                    }
                  >
                    {analysis.narrative.source === 'llm' && analysis.verification.passed
                      ? 'Written by AI and checked against your numbers'
                      : 'Explained by template'}
                  </span>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
                  {analysis.habits.map((habit) => (
                    <HabitCard
                      key={habit.key}
                      habit={habit}
                      overlaps={analysis.overlaps}
                      allHabits={analysis.habits}
                      onViewEvidence={(h) => setSelectedHabitForEvidence(h)}
                    />
                  ))}
                </div>
              </>
            ) : (
              <div className="not-material-box" data-testid="not-material-state">
                <h2 className="not-material-title">{analysis.summary}</h2>
                <p className="not-material-meta">
                  {analysis.dataset.n_trades} trades analysed.
                </p>
                <button type="button" className="primary-btn" onClick={handleStartOver}>
                  Try another month
                </button>
              </div>
            )}

            <DisclaimerFooter disclaimers={analysis.disclaimers} />
          </div>
        )}
      </main>

      {/* Trade Evidence Modal */}
      <TradeEvidenceModal
        habit={selectedHabitForEvidence}
        onClose={() => setSelectedHabitForEvidence(null)}
      />
    </div>
  );
};

export default App;
