import React, { useState } from 'react';
import { type Habit, type OverlapItem, formatInr } from '../types';
import { NextMonthRuleBadge } from './NextMonthRuleBadge';
import { CalcDrawer } from './CalcDrawer';

interface HabitCardProps {
  habit: Habit;
  overlaps: OverlapItem[];
  allHabits: Habit[];
  onViewEvidence: (habit: Habit) => void;
}

export const HabitCard: React.FC<HabitCardProps> = ({
  habit,
  overlaps,
  allHabits,
  onViewEvidence,
}) => {
  const [showCalc, setShowCalc] = useState(false);

  // Confidence label mapping
  let confidenceLabel = 'Low';
  let confidenceClass = 'confidence-low';
  if (habit.confidence >= 0.75) {
    confidenceLabel = 'High';
    confidenceClass = 'confidence-high';
  } else if (habit.confidence >= 0.4) {
    confidenceLabel = 'Medium';
    confidenceClass = 'confidence-medium';
  }

  // Find higher-ranked habit causing overlap if overlap_share > 0
  let overlappingHabitName = 'another habit';
  if (habit.overlap_share > 0) {
    const overlapRecord = overlaps.find(
      (o) => Array.isArray(o.habits) && o.habits[1] === habit.key,
    );
    if (overlapRecord && overlapRecord.habits[0]) {
      const parentKey = overlapRecord.habits[0];
      const parentHabit = allHabits.find((h) => h.key === parentKey);
      if (parentHabit) {
        overlappingHabitName = parentHabit.name;
      }
    }
  }

  return (
    <article className="habit-card" data-testid={`habit-card-${habit.key}`}>
      <header className="habit-header">
        <div className="habit-rank-name">
          <span className="habit-rank-badge">{habit.rank}</span>
          <h3 className="habit-title">{habit.name}</h3>
        </div>

        <span
          className={`confidence-chip ${confidenceClass}`}
          title={`Confidence score: ${habit.confidence.toFixed(2)}`}
        >
          {confidenceLabel} Confidence
        </span>
      </header>

      <div className="habit-cost-row">
        <div className="cost-amount">₹{formatInr(habit.attributed_cost_inr)}</div>

        {habit.overlap_share > 0 && (
          <div
            className="overlap-info"
            title="Trades flagged by two habits are counted once, under the higher-ranked habit."
          >
            <span>
              ₹{formatInr(habit.estimated_cost_inr)} before removing overlap with{' '}
              {overlappingHabitName}
            </span>
          </div>
        )}
      </div>

      <p className="habit-explanation">{habit.explanation}</p>

      <NextMonthRuleBadge rule={habit.rule} />

      <footer className="habit-actions">
        <button
          type="button"
          className="secondary-btn"
          onClick={() => onViewEvidence(habit)}
        >
          Show the trades
        </button>

        <button
          type="button"
          className="secondary-btn"
          onClick={() => setShowCalc(!showCalc)}
          aria-expanded={showCalc}
        >
          {showCalc ? 'Hide calculation' : 'How we calculated this'}
        </button>
      </footer>

      {showCalc && (
        <CalcDrawer
          habitKey={habit.key}
          formulaNote={habit.formula_note}
          metrics={habit.metrics}
        />
      )}
    </article>
  );
};
