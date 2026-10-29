export interface HealthStatus {
  status: string;
}

export interface Habit {
  key: string;
  name: string;
  estimated_cost_inr: number;
  evidence_trade_ids: string[];
  explanation: string;
  next_month_rule: string;
  confidence: number;
  metrics: Record<string, unknown>;
}

export interface AnalysisResponse {
  total_trades_analyzed: number;
  net_pnl_inr: number;
  habits: Habit[];
}
