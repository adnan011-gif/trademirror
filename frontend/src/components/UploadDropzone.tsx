import React from 'react';

interface UploadDropzoneProps {
  onFileSelect: (file: File) => void;
  isLoading?: boolean;
}

export const UploadDropzone: React.FC<UploadDropzoneProps> = ({ onFileSelect: _onFileSelect, isLoading: _isLoading }) => {
  return (
    <div className="upload-dropzone">
      <p>Upload orders CSV</p>
    </div>
  );
};
