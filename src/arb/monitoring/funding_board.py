"""Funding rate monitoring board helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from arb.scanner.funding_scanner import FundingOpportunity, FundingScanner


@dataclass(slots=True, frozen=True)
class FundingBoardRow:
    exchange: str
    symbol: str
    gross_rate: str
    net_rate: str
    annualized_net_rate: str
    spread_bps: str
    liquidity_usd: str
    next_funding_time: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
        snapshots: list[dict[str, Any]],
        *,
        opportunities: list[FundingOpportunity] | None = None,
    ) -> list[FundingBoardRow]:
        candidates = opportunities or self.scanner.scan(snapshots)
        funding_index = {
            (str(snapshot["funding"]["exchange"]), str(snapshot["funding"]["symbol"])): snapshot["funding"]
            for snapshot in snapshots
            if snapshot.get("funding")
        }
        rows = [
            FundingBoardRow(
                exchange=item.exchange,
                symbol=item.symbol,
                gross_rate=str(item.gross_rate),
                net_rate=str(item.net_rate),
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
        funding_index: dict[tuple[str, str], dict[str, Any]],
        exchange: str,
        symbol: str,
    ) -> str | None:
        funding = funding_index.get((exchange, symbol))
        if funding is None:
            return None
        value = funding.get("next_funding_time")
        return None if value is None else str(value)
