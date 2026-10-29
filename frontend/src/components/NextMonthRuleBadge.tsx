import React from 'react';

interface NextMonthRuleBadgeProps {
  rule: string;
}

export const NextMonthRuleBadge: React.FC<NextMonthRuleBadgeProps> = ({ rule }) => {
  return (
    <div className="rule-box" data-testid="next-month-rule">
      <span className="rule-label">Next month's rule</span>
      <p className="rule-text">{rule}</p>
    </div>
  );
};
