import React from 'react';
import type { Habit } from '../types';

interface HabitCardProps {
  habit: Habit;
  onViewEvidence: (habit: Habit) => void;
}

export const HabitCard: React.FC<HabitCardProps> = ({ habit, onViewEvidence: _onViewEvidence }) => {
  return (
    <div className="habit-card">
      <h3>{habit.name}</h3>
      <p>Estimated Cost: ₹{habit.estimated_cost_inr.toLocaleString('en-IN')}</p>
    </div>
  );
};
