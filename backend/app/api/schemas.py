"""API request and response schemas for TradeMirror."""

from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Health check response schema."""

    status: str = "ok"


class SampleItemResponse(BaseModel):
    """Schema for built-in sample dataset catalogue items."""

    name: str
    label: str
    description: str


class EvidenceTrade(BaseModel):
    """Granular trade record supporting diagnosed behavioral habits."""

    trade_id: str
    trading_date: str
    entry_time: str
    exit_time: str
    symbol: str
    instrument_type: str
    strike: float | None = None
    direction: str
    quantity: int
    lots: float
    hold_minutes: float
    gross_pnl: float


class HabitResponseItem(BaseModel):
    """Schema for an individual diagnosed behavioral habit."""

    key: str
    name: str
    rank: int
    attributed_cost_inr: float
    estimated_cost_inr: float
    overlap_share: float
    confidence: float
    explanation: str
    rule: str
    formula_note: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    evidence_trades: list[EvidenceTrade] = Field(default_factory=list)
    evidence_total: int
    evidence_truncated: bool


class DatasetInfo(BaseModel):
    """Audit and ingestion metadata for the analyzed order set."""

    source: str
    n_orders_raw: int
    n_orders_kept: int
    n_trades: int
    counts: dict[str, int] = Field(default_factory=dict)


class ContextInfo(BaseModel):
    """Portfolio context metrics for the analysis period."""

    gross_pnl_inr: float
    gross_loss_inr: float
    win_rate: float
    total_attributed_cost_inr: float


class WarningItem(BaseModel):
    """Non-fatal ingest warning audit entry."""

    code: str
    row_number: int | None = None
    order_id: str | None = None
    message: str


class NarrativeInfo(BaseModel):
    """Metadata regarding narrative generation provenance."""

    source: str
    fallback_reason: str | None = None
    llm_attempts: int = 0


class VerificationInfo(BaseModel):
    """Grounding verifier execution audit report."""

    passed: bool
    checked_numbers: list[float] = Field(default_factory=list)
    checked_trade_ids: list[str] = Field(default_factory=list)
    failures: list[dict[str, Any]] = Field(default_factory=list)


class AnalysisResponse(BaseModel):
    """Comprehensive analysis response returned by /analyze and /sample/{name}."""

    dataset: DatasetInfo
    context: ContextInfo
    material: bool
    summary: str
    habits: list[HabitResponseItem] = Field(default_factory=list)
    overlaps: list[dict[str, Any]] = Field(default_factory=list)
    dropped: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[WarningItem] = Field(default_factory=list)
    warnings_total: int = 0
    pairing_anomalies: list[str] = Field(default_factory=list)
    narrative: NarrativeInfo
    verification: VerificationInfo
    detector_errors: list[str] = Field(default_factory=list)
    disclaimers: list[str] = Field(
        default_factory=lambda: [
            "Gross P&L only; brokerage and taxes not included.",
            "Habit costs are estimates from your order history, not predictions.",
            "This is not investment advice.",
        ]
    )
