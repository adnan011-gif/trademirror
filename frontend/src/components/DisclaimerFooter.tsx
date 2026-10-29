import React from 'react';

interface DisclaimerFooterProps {
  disclaimers: string[];
}

export const DisclaimerFooter: React.FC<DisclaimerFooterProps> = ({ disclaimers }) => {
  if (!disclaimers || disclaimers.length === 0) return null;

  return (
    <footer className="disclaimer-footer" data-testid="disclaimer-footer">
      {disclaimers.map((disclaimer, index) => (
        <p key={index}>{disclaimer}</p>
      ))}
    </footer>
  );
};
