import React, { useEffect, useRef } from 'react';
import { type Habit, formatInr } from '../types';

interface TradeEvidenceModalProps {
  habit: Habit | null;
  onClose: () => void;
}

export const TradeEvidenceModal: React.FC<TradeEvidenceModalProps> = ({ habit, onClose }) => {
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const previouslyFocusedElement = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!habit) return;

    previouslyFocusedElement.current = document.activeElement as HTMLElement;

    // Focus close button on open
    const focusTimer = setTimeout(() => {
      closeButtonRef.current?.focus();
    }, 50);

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
        return;
      }

      // Trap focus
      if (event.key === 'Tab' && dialogRef.current) {
        const focusable = dialogRef.current.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        );
        if (focusable.length === 0) return;

        const firstElement = focusable[0];
        const lastElement = focusable[focusable.length - 1];

        if (event.shiftKey) {
          if (document.activeElement === firstElement) {
            lastElement.focus();
            event.preventDefault();
          }
        } else {
          if (document.activeElement === lastElement) {
            firstElement.focus();
            event.preventDefault();
          }
        }
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      clearTimeout(focusTimer);
      document.removeEventListener('keydown', handleKeyDown);
      previouslyFocusedElement.current?.focus();
    };
  }, [habit, onClose]);

  if (!habit) return null;

  const shownCount = habit.evidence_trades.length;

  return (
    <div
      className="modal-overlay"
      onClick={onClose}
      data-testid="modal-overlay"
    >
      <div
        ref={dialogRef}
        className="modal-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-dialog-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <h2 id="modal-dialog-title" className="modal-title">
            Flagged Trades: {habit.name}
          </h2>
          <button
            ref={closeButtonRef}
            type="button"
            className="modal-close-btn"
            onClick={onClose}
            aria-label="Close dialog"
          >
            &times;
          </button>
        </div>

        <div className="modal-body">
          {habit.evidence_truncated && (
            <div className="truncation-note">
              Showing the {shownCount} largest losses of {habit.evidence_total} flagged trades
            </div>
          )}

          <div className="table-container">
            <table className="evidence-table">
              <thead>
                <tr>
                  <th scope="col">Date</th>
                  <th scope="col">Scrip</th>
                  <th scope="col">Direction</th>
                  <th scope="col">Lots</th>
                  <th scope="col">Hold Time</th>
                  <th scope="col">P&amp;L</th>
                </tr>
              </thead>
              <tbody>
                {habit.evidence_trades.map((t) => {
                  const isProfit = t.gross_pnl > 0;
                  const isLoss = t.gross_pnl < 0;
                  const sign = isProfit ? '+' : isLoss ? '-' : '';
                  const formattedPnl = `${sign}₹${formatInr(Math.abs(t.gross_pnl))}`;
                  const pnlClass = isProfit ? 'pnl-pos' : isLoss ? 'pnl-neg' : '';

                  const scripLabel = t.strike
                    ? `${t.symbol} ${formatInr(t.strike)} ${t.instrument_type}`
                    : `${t.symbol} ${t.instrument_type}`;

                  return (
                    <tr key={t.trade_id}>
                      <td>{t.trading_date}</td>
                      <td>{scripLabel}</td>
                      <td>{t.direction}</td>
                      <td>{t.lots}</td>
                      <td>{t.hold_minutes}m</td>
                      <td className={pnlClass}>{formattedPnl}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
};
