"""Control API schemas."""

from __future__ import annotations

from pydantic import Field

from arb.schemas.base import ArbFrozenModel, SerializableValue


class HealthResponse(ArbFrozenModel):
    status: str


class PositionResponse(ArbFrozenModel):
    exchange: str
    symbol: str
    market_type: str = "unknown"
    quantity: str
    direction: str


class StrategyResponse(ArbFrozenModel):
    name: str
    status: str


class OrderResponse(ArbFrozenModel):
    exchange: str
    symbol: str
    market_type: str = "unknown"
    order_id: str
    status: str
    filled_quantity: str


class WorkflowResponse(ArbFrozenModel):
    workflow_id: str
    workflow_type: str = "unknown"
    exchange: str
    symbol: str
    status: str
    payload: dict[str, SerializableValue] = Field(default_factory=dict)


class FundingBoardResponse(ArbFrozenModel):
    exchange: str
    symbol: str
    gross_rate: str = "0"
    net_rate: str
    funding_interval_hours: int = 8
    annualized_net_rate: str
    spread_bps: str
    liquidity_usd: str
    next_funding_time: str | None = None


class CommandRequest(ArbFrozenModel):
    action: str
    target: str
    requested_by: str
    require_confirmation: bool = False
    payload: dict[str, SerializableValue] = Field(default_factory=dict)


class CommandResponse(ArbFrozenModel):
    accepted: bool
    command_id: str
    status: str


class CommandQueueSnapshot(ArbFrozenModel):
    queued: list[str]
    pending_confirmation: list[str]
