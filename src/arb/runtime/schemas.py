"""Typed runtime state and recovery models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import ConfigDict, Field

from arb.market.schemas import MarketSnapshot
from arb.portfolio.reconciler import ReconciliationReport
from arb.scanner.funding_scanner import FundingOpportunity
from arb.schemas.base import ArbFrozenModel, ArbModel, SerializableValue
from arb.strategy.engine import StrategyState
from arb.workflows.close_position import ClosePositionResult
from arb.workflows.open_position import OpenPositionResult


class ActiveFundingArb(ArbModel):
    workflow_id: str
    exchange: str
    symbol: str
    quantity: Decimal
    spot_quantity: Decimal
    perp_quantity: Decimal
    opened_at: datetime
    liquidation_price: Decimal | None = None
    route: object | None = None
    state: StrategyState = Field(default_factory=StrategyState)

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        arbitrary_types_allowed=True,
    )


class CrossExchangeOpportunity(ArbFrozenModel):
    symbol: str
    long_exchange: str
    short_exchange: str
    spread_rate: Decimal
    long_price: Decimal
    short_price: Decimal


class ActiveCrossExchangeArb(ArbModel):
    workflow_id: str
    symbol: str
    long_exchange: str
    short_exchange: str
    quantity: Decimal
    long_quantity: Decimal
    short_quantity: Decimal
    opened_at: datetime
    state: StrategyState = Field(default_factory=StrategyState)

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        arbitrary_types_allowed=True,
    )


class WorkflowStateRecord(ArbFrozenModel):
    workflow_id: str
    workflow_type: str
    exchange: str
    symbol: str
    status: str
    payload: dict[str, SerializableValue] = Field(default_factory=dict)
    updated_at: str | None = None


class RealtimeScanResult(ArbFrozenModel):
    snapshots: list[MarketSnapshot]
    opportunities: list[FundingOpportunity]
    output: list[str]


class FundingArbRunResult(ArbFrozenModel):
    scan: RealtimeScanResult
    opened: list[OpenPositionResult]
    closed: list[ClosePositionResult]
    active: list[ActiveFundingArb]

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        arbitrary_types_allowed=True,
    )


class CrossExchangeRunResult(ArbFrozenModel):
    snapshots: list[MarketSnapshot]
    opportunities: list[CrossExchangeOpportunity]
    opened: list[OpenPositionResult]
    closed: list[ClosePositionResult]
    active: list[ActiveCrossExchangeArb]

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        arbitrary_types_allowed=True,
    )


class RecoveryPlan(ArbModel):
    workflows: list[WorkflowStateRecord]
    reconciliation: ReconciliationReport
    exchange_positions: list[object] = Field(default_factory=list)
    exchange_orders: list[object] = Field(default_factory=list)

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        arbitrary_types_allowed=True,
    )
