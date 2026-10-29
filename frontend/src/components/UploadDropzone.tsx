import React, { useRef, useState } from 'react';

interface UploadDropzoneProps {
  onFileSelect: (file: File) => void;
  isLoading?: boolean;
}

const CANONICAL_COLUMNS = [
  'order_id',
  'timestamp',
  'symbol',
  'instrument_type',
  'strike',
  'expiry',
  'side',
  'quantity',
  'lot_size',
  'price',
  'status',
];

const MAX_BYTES = 5 * 1024 * 1024; // 5 MB

export const UploadDropzone: React.FC<UploadDropzoneProps> = ({
  onFileSelect,
  isLoading = false,
}) => {
  const [isDragOver, setIsDragOver] = useState(false);
  const [clientError, setClientError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const validateAndUpload = (file: File) => {
    setClientError(null);

    if (!file.name.toLowerCase().endsWith('.csv')) {
      setClientError('Please select a valid CSV file (.csv).');
      return;
    }

    if (file.size > MAX_BYTES) {
      setClientError('File exceeds the 5 MB limit. Please select a smaller order history file.');
      return;
    }

    onFileSelect(file);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    if (!isLoading) setIsDragOver(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    if (isLoading) return;

    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      validateAndUpload(e.dataTransfer.files[0]);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      validateAndUpload(e.target.files[0]);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
      <div
        className={`upload-card ${isDragOver ? 'drag-over' : ''} ${isLoading ? 'disabled' : ''}`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => !isLoading && fileInputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if ((e.key === 'Enter' || e.key === ' ') && !isLoading) {
            e.preventDefault();
            fileInputRef.current?.click();
          }
        }}
        aria-label="Upload orders CSV"
        data-testid="upload-dropzone"
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".csv,text/csv"
          onChange={handleFileChange}
          style={{ display: 'none' }}
          disabled={isLoading}
          aria-hidden="true"
        />

        <p className="upload-title">Or upload your own monthly orders CSV</p>
        <p className="upload-subtitle">Drag and drop your file here, or click to browse</p>

        <button
          type="button"
          className="upload-file-button"
          onClick={(e) => {
            e.stopPropagation();
            fileInputRef.current?.click();
          }}
          disabled={isLoading}
        >
          Select CSV File
        </button>

        {clientError && (
          <p style={{ color: 'var(--loss)', fontSize: '0.85rem', fontWeight: 600 }}>
            {clientError}
          </p>
        )}
      </div>

      <details className="columns-expander">
        <summary>What columns do I need?</summary>
        <div className="columns-list">
          {CANONICAL_COLUMNS.map((col) => (
            <span key={col} className="col-tag">
              {col}
            </span>
          ))}
        </div>
      </details>
    </div>
  );
};
