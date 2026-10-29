import React from 'react';
import type { WarningItem } from '../types';

interface WarningsBannerProps {
  warningsTotal: number;
  warnings: WarningItem[];
  counts: Record<string, number>;
}

export const WarningsBanner: React.FC<WarningsBannerProps> = ({
  warningsTotal,
  warnings,
  counts,
}) => {
  if (warningsTotal <= 0) return null;

  const rowWord = warningsTotal === 1 ? 'row' : 'rows';

  // Audit count pills
  const relevantCounts: Array<{ label: string; count: number }> = [];
  if (counts.duplicate_orders) relevantCounts.push({ label: 'Duplicates', count: counts.duplicate_orders });
  if (counts.rejected_orders) relevantCounts.push({ label: 'Rejected', count: counts.rejected_orders });
  if (counts.missing_price) relevantCounts.push({ label: 'Missing Price', count: counts.missing_price });
  if (counts.invalid_syntax) relevantCounts.push({ label: 'Invalid Format', count: counts.invalid_syntax });

  const shownWarnings = warnings.slice(0, 10);

  return (
    <details className="warnings-banner" data-testid="warnings-banner">
      <summary className="warnings-summary">
        We skipped or adjusted {warningsTotal} {rowWord}
      </summary>

      <div className="warnings-body">
        {relevantCounts.length > 0 && (
          <div className="counts-pill-row">
            {relevantCounts.map((c) => (
              <span key={c.label} className="count-pill">
                {c.label}: {c.count}
              </span>
            ))}
          </div>
        )}

        <ul style={{ paddingLeft: '1.25rem', marginTop: '0.25rem' }}>
          {shownWarnings.map((w, idx) => (
            <li key={`${w.code}-${idx}`}>
              {w.row_number ? `Line ${w.row_number}: ` : ''}
              {w.message}
            </li>
          ))}
        </ul>
      </div>
    </details>
  );
};
