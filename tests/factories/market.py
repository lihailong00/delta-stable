"""Market-data test factories."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from arb.market.schemas import MarketSnapshot
from arb.models import FundingRate, MarketType, Ticker


def build_market_snapshot(
    exchange: str,
    symbol: str,
    *,
    rate: str = "0.0005",
    funding_interval_hours: int = 8,
    bid: str = "100.0",
    ask: str = "100.2",
    last: str = "100.1",
    liquidity_usd: str | None = None,
    top_ask_size: str | None = "10",
    market_type: MarketType = MarketType.PERPETUAL,
) -> MarketSnapshot:
    ts = datetime(2026, 3, 17, tzinfo=timezone.utc)
    return MarketSnapshot(
        ticker=Ticker(
            exchange=exchange,
            symbol=symbol,
            market_type=market_type,
            bid=Decimal(bid),
            ask=Decimal(ask),
            last=Decimal(last),
            ts=ts,
        ),
        funding=FundingRate(
            exchange=exchange,
            symbol=symbol,
            rate=Decimal(rate),
            predicted_rate=Decimal(rate),
            funding_interval_hours=funding_interval_hours,
            next_funding_time=datetime(2026, 3, 17, 8, tzinfo=timezone.utc),
            ts=ts,
        ),
        liquidity_usd=Decimal(liquidity_usd) if liquidity_usd is not None else None,
        top_ask_size=Decimal(top_ask_size) if top_ask_size is not None else None,
    )
