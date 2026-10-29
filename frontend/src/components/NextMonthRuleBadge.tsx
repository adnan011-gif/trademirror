import React from 'react';

interface NextMonthRuleBadgeProps {
  rule: string;
}

export const NextMonthRuleBadge: React.FC<NextMonthRuleBadgeProps> = ({ rule }) => {
  return (
    <div className="next-month-rule-badge">
      <span>Rule: {rule}</span>
    </div>
  );
};
