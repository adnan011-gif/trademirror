import React from 'react';
import type { Habit } from '../types';

interface TradeEvidenceModalProps {
  habit: Habit | null;
  onClose: () => void;
}

export const TradeEvidenceModal: React.FC<TradeEvidenceModalProps> = ({ habit, onClose }) => {
  if (!habit) return null;
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <h3>Evidence for {habit.name}</h3>
        <button onClick={onClose}>Close</button>
      </div>
    </div>
  );
};
