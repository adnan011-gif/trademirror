/**
 * Type definitions mirroring the TradeMirror API analysis response.
 */

export interface SampleItem {
  name: string;
  label: string;
  description: string;
}

export interface EvidenceTrade {
  trade_id: string;
  trading_date: string;
  entry_time: string;
  exit_time: string;
  symbol: string;
  instrument_type: string;
  strike: number | null;
  direction: string;
  quantity: number;
  lots: number;
  hold_minutes: number;
  gross_pnl: number;
}

export interface Habit {
  key: string;
  name: string;
  rank: number;
  attributed_cost_inr: number;
  estimated_cost_inr: number;
  overlap_share: number;
  confidence: number;
  explanation: string;
  rule: string;
  formula_note: string;
  metrics: Record<string, unknown>;
  evidence_trades: EvidenceTrade[];
  evidence_total: number;
  evidence_truncated: boolean;
}

export interface DatasetInfo {
  source: string;
  n_orders_raw: number;
  n_orders_kept: number;
  n_trades: number;
  counts: Record<string, number>;
}

export interface ContextInfo {
  gross_pnl_inr: number;
  gross_loss_inr: number;
  win_rate: number;
  total_attributed_cost_inr: number;
}

export interface WarningItem {
  code: string;
  row_number: number | null;
  order_id: string | null;
  message: string;
}

export interface NarrativeInfo {
  source: 'llm' | 'template';
  fallback_reason: string | null;
  llm_attempts: number;
}

export interface VerificationInfo {
  passed: boolean;
  checked_numbers: number[];
  checked_trade_ids: string[];
  failures: Array<Record<string, unknown>>;
}

export interface OverlapItem {
  habits: string[];
  shared_trade_ids?: string[];
  [key: string]: unknown;
}

export interface DroppedItem {
  habit: string;
  reason: string;
  [key: string]: unknown;
}

export interface AnalysisResponse {
  dataset: DatasetInfo;
  context: ContextInfo;
  material: boolean;
  summary: string;
  habits: Habit[];
  overlaps: OverlapItem[];
  dropped: DroppedItem[];
  warnings: WarningItem[];
  warnings_total: number;
  pairing_anomalies: string[];
  narrative: NarrativeInfo;
  verification: VerificationInfo;
  detector_errors: string[];
  disclaimers: string[];
}

/**
 * Runtime guard validating that an untyped object satisfies AnalysisResponse schema.
 */
export function isAnalysisResponse(obj: unknown): obj is AnalysisResponse {
  if (obj === null || typeof obj !== 'object') {
    return false;
  }

  const candidate = obj as Record<string, unknown>;

  // Check essential top-level fields
  if (
    typeof candidate.material !== 'boolean' ||
    typeof candidate.summary !== 'string' ||
    !Array.isArray(candidate.habits) ||
    !Array.isArray(candidate.disclaimers)
  ) {
    return false;
  }

  // Validate dataset object
  if (candidate.dataset === null || typeof candidate.dataset !== 'object') {
    return false;
  }
  const dataset = candidate.dataset as Record<string, unknown>;
  if (typeof dataset.source !== 'string' || typeof dataset.n_trades !== 'number') {
    return false;
  }

  // Validate context object
  if (candidate.context === null || typeof candidate.context !== 'object') {
    return false;
  }
  const context = candidate.context as Record<string, unknown>;
  if (
    typeof context.gross_pnl_inr !== 'number' ||
    typeof context.total_attributed_cost_inr !== 'number'
  ) {
    return false;
  }

  // Validate habits array
  for (const habit of candidate.habits) {
    if (habit === null || typeof habit !== 'object') {
      return false;
    }
    const h = habit as Record<string, unknown>;
    if (
      typeof h.key !== 'string' ||
      typeof h.name !== 'string' ||
      typeof h.attributed_cost_inr !== 'number' ||
      typeof h.rule !== 'string' ||
      !Array.isArray(h.evidence_trades)
    ) {
      return false;
    }
  }

  return true;
}

/**
 * Format numbers according to Indian grouping conventions (en-IN).
 */
export function formatInr(amount: number, decimals: number = 0): string {
  const val = decimals === 0 ? Math.round(amount) : amount;
  return new Intl.NumberFormat('en-IN', {
    maximumFractionDigits: decimals,
    minimumFractionDigits: decimals,
  }).format(val);
}

