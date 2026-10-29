import React from 'react';
import { type ContextInfo, type DatasetInfo, formatInr } from '../types';

interface HeadlineProps {
  nHabits: number;
  context: ContextInfo;
  dataset: DatasetInfo;
}

export const Headline: React.FC<HeadlineProps> = ({ nHabits, context, dataset }) => {
  const habitWord = nHabits === 1 ? 'habit' : 'habits';
  const totalCostFormatted = formatInr(context.total_attributed_cost_inr, 0);

  const winRatePercent = (context.win_rate * 100).toFixed(1).replace(/\.0$/, '');

  const isProfit = context.gross_pnl_inr > 0;
  const isLoss = context.gross_pnl_inr < 0;
  const pnlSign = isProfit ? '+' : isLoss ? '-' : '';
  const absPnlFormatted = formatInr(Math.abs(context.gross_pnl_inr), 0);

  const showProfitableNote =
    context.gross_pnl_inr > 0 && context.total_attributed_cost_inr > 0;

  return (
    <div className="headline-box" data-testid="headline-box">
      <h2 className="headline-title">
        {nHabits} {habitWord} cost you about ₹{totalCostFormatted} this month
      </h2>

      <p className="headline-meta">
        {dataset.n_trades} trades, {winRatePercent}% winners, gross P&amp;L {pnlSign}₹{absPnlFormatted}.
      </p>

      {showProfitableNote && (
        <p className="profitable-note">
          Your month was profitable overall; these costs are what these habits took out of it.
        </p>
      )}
    </div>
  );
};
