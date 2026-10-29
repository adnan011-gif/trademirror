import React from 'react';
import { formatInr } from '../types';

interface CalcDrawerProps {
  habitKey: string;
  formulaNote: string;
  metrics: Record<string, unknown>;
}

const COST_MEASURES: Record<string, string> = {
  holding_losers: 'extra loss beyond what you normally lose on a losing trade',
  revenge_trading: 'net loss on these re-entries',
  overtrading: 'net loss on the extra trades',
  oversizing: 'extra loss attributable to the larger size',
  averaging_down: 'net loss on the added positions',
};

function humanizeKey(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase())
    .replace('Inr', '(INR)')
    .replace('Min', 'Minutes');
}

function formatMetricValue(value: unknown): string {
  if (typeof value === 'number') {
    if (Number.isInteger(value)) {
      return value.toString();
    }
    return formatInr(value, 2);
  }
  if (typeof value === 'boolean') {
    return value ? 'Yes' : 'No';
  }
  if (value === null || value === undefined) {
    return 'None';
  }
  return String(value);
}

export const CalcDrawer: React.FC<CalcDrawerProps> = ({ habitKey, formulaNote, metrics }) => {
  const costMeasure = COST_MEASURES[habitKey] || 'cost attributed to this habit';

  const metricEntries = Object.entries(metrics).filter(([key]) => key !== 'trade_ids');

  return (
    <div className="calc-drawer" data-testid="calc-drawer">
      {formulaNote && <p className="drawer-formula">{formulaNote}</p>}

      {metricEntries.length > 0 && (
        <div className="metrics-list">
          {metricEntries.map(([k, v]) => (
            <div key={k} className="metric-item">
              <span className="metric-key">{humanizeKey(k)}</span>
              <span className="metric-val">{formatMetricValue(v)}</span>
            </div>
          ))}
        </div>
      )}

      <p className="drawer-cost-definition">
        <strong>Cost measured:</strong> {costMeasure}.
      </p>
    </div>
  );
};
