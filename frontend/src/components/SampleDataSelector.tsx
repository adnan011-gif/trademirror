import React from 'react';

interface SampleDataSelectorProps {
  onSelectSample: (sampleName: string) => void;
  isLoading?: boolean;
}

export const SampleDataSelector: React.FC<SampleDataSelectorProps> = ({
  onSelectSample: _onSelectSample,
  isLoading: _isLoading,
}) => {
  return (
    <div className="sample-selector">
      <p>Load Sample Dataset</p>
    </div>
  );
};
