"""Structured output of the agent."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

DISCLAIMER = (
    "Advisory output only, not financial advice. CFDs are leveraged and can lose money rapidly; "
    "gaps, overnight financing and slippage can make losses exceed the planned risk."
)


class Evidence(BaseModel):
    tool: str = Field(description="MCP tool whose output supports the point")
    finding: str
    direction: Literal["bullish", "bearish", "neutral"]


class RiskPlan(BaseModel):
    entry: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    position_size_units: float = Field(description="CFD units (1 unit = 1 index point per point of price)")
    risk_amount: float
    notional: float
    margin_required: float


class Recommendation(BaseModel):
    action: Literal["BUY", "SELL", "HOLD"]
    confidence: float = Field(ge=0, le=1)
    horizon: str = "swing (days to weeks)"
    summary: str
    evidence: list[Evidence]
    risks: list[str]
    risk_plan: Optional[RiskPlan] = None
    disclaimer: str = DISCLAIMER
