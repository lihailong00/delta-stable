"""Typed schemas for backtest datasets, points and reports."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import ConfigDict, Field

from arb.funding import DEFAULT_FUNDING_INTERVAL_HOURS
from arb.schemas.base import ArbFrozenModel


class MonthlySourceUrls(ArbFrozenModel):
    funding_url: str
    kline_url: str


class FundingCsvRow(ArbFrozenModel):
    calc_time: int
    last_funding_rate: Decimal
    funding_interval_hours: int | None = Field(default=None, ge=1)

    model_config = ConfigDict(extra="ignore", frozen=True)


class KlineCsvRow(ArbFrozenModel):
    open_time: int
    close: Decimal
    quote_volume: Decimal = Decimal("0")

    model_config = ConfigDict(extra="ignore", frozen=True)


class MergedBacktestRow(ArbFrozenModel):
    exchange: str
    symbol: str
    ts: datetime
    price: Decimal
    funding_rate: Decimal
    funding_interval_hours: int = Field(default=DEFAULT_FUNDING_INTERVAL_HOURS, ge=1)
    liquidity_usd: Decimal = Decimal("0")
    source_month: str


class SymbolDataset(ArbFrozenModel):
    symbol: str
    rows: list[MergedBacktestRow]
    missing_months: list[str]


class HistoricalPoint(ArbFrozenModel):
    ts: datetime
    price: Decimal
    funding_rate: Decimal
    liquidity_usd: Decimal
    funding_interval_hours: int = Field(default=DEFAULT_FUNDING_INTERVAL_HOURS, ge=1)


class BacktestTrade(ArbFrozenModel):
    opened_at: datetime
    closed_at: datetime
    holding_periods: int
    funding_pnl: Decimal
    open_fee_cost: Decimal
    close_fee_cost: Decimal
    rebalance_fee_cost: Decimal
    borrow_cost: Decimal
    net_pnl: Decimal


class BacktestResult(ArbFrozenModel):
    total_return: Decimal
    max_drawdown: Decimal
    average_liquidity_usd: Decimal
    equity_curve: list[Decimal]
    funding_pnl: Decimal = Decimal("0")
    open_fee_cost: Decimal = Decimal("0")
    close_fee_cost: Decimal = Decimal("0")
    rebalance_fee_cost: Decimal = Decimal("0")
    borrow_cost: Decimal = Decimal("0")
    trades: list[BacktestTrade] = Field(default_factory=list)
    holding_periods: int = 0
    trade_count: int = 0
    capital_utilization: Decimal = Decimal("0")
    average_trade_return: Decimal = Decimal("0")


class BacktestTradeReport(ArbFrozenModel):
    opened_at: str
    closed_at: str
    holding_periods: int
    funding_pnl: str
    open_fee_cost: str
    close_fee_cost: str
    rebalance_fee_cost: str
    borrow_cost: str
    net_pnl: str


class BacktestReport(ArbFrozenModel):
    total_return: str
    max_drawdown: str
    average_liquidity_usd: str
    funding_pnl: str
    open_fee_cost: str
    close_fee_cost: str
    rebalance_fee_cost: str
    borrow_cost: str
    trade_count: int
    holding_periods: int
    capital_utilization: str
    average_trade_return: str
    trades: list[BacktestTradeReport]
    num_points: int
