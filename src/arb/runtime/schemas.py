"""Typed runtime state and recovery models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import ConfigDict, Field

from arb.portfolio.reconciler import ReconciliationReport
from arb.schemas.base import ArbFrozenModel, ArbModel, SerializableValue
from arb.strategy.engine import StrategyState


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
