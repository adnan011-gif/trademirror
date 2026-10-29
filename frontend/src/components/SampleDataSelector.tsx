import React, { useState } from 'react';
import type { SampleItem } from '../types';

interface SampleDataSelectorProps {
  samples: SampleItem[];
  onSelectSample: (sampleName: string) => void;
  isLoading?: boolean;
}

export const SampleDataSelector: React.FC<SampleDataSelectorProps> = ({
  samples,
  onSelectSample,
  isLoading = false,
}) => {
  const [selected, setSelected] = useState<string>('mixed');

  const currentSample =
    samples.find((s) => s.name === selected) ||
    samples.find((s) => s.name === 'mixed') ||
    samples[0];

  const handleRun = () => {
    if (currentSample) {
      onSelectSample(currentSample.name);
    }
  };

  return (
    <section className="sample-card" aria-labelledby="sample-selector-heading">
      <span id="sample-selector-heading" className="section-label">
        Primary Option
      </span>
      <h3 style={{ fontSize: '1.25rem', fontWeight: 600 }}>Try a sample month</h3>

      <div className="sample-selector-row">
        <label htmlFor="sample-dataset-select" className="visually-hidden" style={{ display: 'none' }}>
          Select sample dataset
        </label>
        <select
          id="sample-dataset-select"
          className="sample-select"
          value={currentSample ? currentSample.name : 'mixed'}
          onChange={(e) => setSelected(e.target.value)}
          disabled={isLoading}
        >
          {samples.map((s) => (
            <option key={s.name} value={s.name}>
              {s.label}
            </option>
          ))}
        </select>

        <button
          type="button"
          className="primary-btn"
          onClick={handleRun}
          disabled={isLoading}
        >
          {isLoading ? 'Analyzing...' : 'Run Analysis'}
        </button>
      </div>

      {currentSample && (
        <p className="sample-description-text">{currentSample.description}</p>
      )}
    </section>
  );
};
