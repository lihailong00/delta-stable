"""Funding rate monitoring board helpers."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import cast

from arb.market.schemas import MarketSnapshot, coerce_market_snapshot
from arb.schemas.base import ArbFrozenModel, SerializableValue
from arb.scanner.funding_scanner import FundingOpportunity, FundingScanner


class FundingBoardRow(ArbFrozenModel):
    exchange: str
    symbol: str
    gross_rate: str
    net_rate: str
    funding_interval_hours: int
    annualized_net_rate: str
    spread_bps: str
    liquidity_usd: str
    next_funding_time: str | None = None


class FundingBoard:
    """Build sorted, filtered funding monitoring rows from market snapshots."""

    def __init__(
        self,
        *,
        scanner: FundingScanner | None = None,
        min_liquidity_usd: Decimal = Decimal("0"),
        top_n: int = 20,
    ) -> None:
        self.scanner = scanner or FundingScanner(min_liquidity_usd=min_liquidity_usd)
        self.min_liquidity_usd = min_liquidity_usd
        self.top_n = top_n

    def build_rows(
        self,
        snapshots: list[MarketSnapshot | Mapping[str, SerializableValue]],
        *,
        opportunities: list[FundingOpportunity] | None = None,
    ) -> list[FundingBoardRow]:
        normalized = [self._coerce_snapshot(snapshot) for snapshot in snapshots]
        candidates = opportunities or self.scanner.scan(normalized)
        funding_index = {
            (snapshot.funding.exchange, snapshot.funding.symbol): snapshot.funding
            for snapshot in normalized
            if snapshot.funding is not None
        }
        rows = [
            FundingBoardRow(
                exchange=item.exchange,
                symbol=item.symbol,
                gross_rate=str(item.gross_rate),
                net_rate=str(item.net_rate),
                funding_interval_hours=item.funding_interval_hours,
                annualized_net_rate=str(item.annualized_net_rate),
                spread_bps=str(item.spread_bps),
                liquidity_usd=str(item.liquidity_usd),
                next_funding_time=self._next_funding_time(funding_index, item.exchange, item.symbol),
            )
            for item in candidates
            if item.liquidity_usd >= self.min_liquidity_usd
        ]
        rows.sort(key=lambda item: Decimal(item.annualized_net_rate), reverse=True)
        return rows[: self.top_n]

    @staticmethod
    def _next_funding_time(
        funding_index: dict[tuple[str, str], object],
        exchange: str,
        symbol: str,
    ) -> str | None:
        funding = cast(object | None, funding_index.get((exchange, symbol)))
        if funding is None:
            return None
        value = getattr(funding, "next_funding_time", None)
        return None if value is None else str(value)

    @staticmethod
    def _coerce_snapshot(
        snapshot: MarketSnapshot | Mapping[str, SerializableValue],
    ) -> MarketSnapshot:
        if isinstance(snapshot, MarketSnapshot):
            return snapshot
        return coerce_market_snapshot(dict(snapshot))
