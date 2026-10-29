"""API request and response schemas."""

from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Health check response schema."""

    status: str = "ok"


class HabitResponse(BaseModel):
    """Schema for an individual diagnosed habit."""

    key: str
    name: str
    estimated_cost_inr: float
    evidence_trade_ids: list[str]
    explanation: str
    next_month_rule: str
    confidence: float
    metrics: dict[str, Any] = Field(default_factory=dict)


class AnalysisResponse(BaseModel):
    """Schema returned by POST /api/analyze."""

    total_trades_analyzed: int
    net_pnl_inr: float
    habits: list[HabitResponse]
