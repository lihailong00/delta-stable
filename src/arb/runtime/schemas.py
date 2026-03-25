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
    # === 身份标识 ===
    workflow_id: str  # 唯一标识符，如 "funding_spot_perp:binance:BTCUSDT"

    # === 基础信息 ===
    exchange: str  # 交易所，如 "binance"
    symbol: str  # 交易对，如 "BTCUSDT"

    # === 仓位信息 ===
    spot_quantity: Decimal  # 现货腿的实际数量
    perp_quantity: Decimal  # 永续合约腿的实际数量

    # === 时间信息 ===
    opened_at: datetime  # 开仓时间

    # === 风控信息 ===
    liquidation_price: Decimal | None = None  # 强平价格（如果有）

    # === 策略信息 ===
    route: object | None = None  # 执行路径（可选）
    state: StrategyState = Field(default_factory=StrategyState)  # 策略状态（如是否已对冲）

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
