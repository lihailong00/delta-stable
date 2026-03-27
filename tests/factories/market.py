"""Market-data test factories."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from arb.market.schemas import MarketSnapshot
from arb.models import FundingRate, MarketType, OrderBook, OrderBookLevel, Ticker


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
    bid_levels: tuple[tuple[str, str], ...] | None = None,
    ask_levels: tuple[tuple[str, str], ...] | None = None,
    market_type: MarketType = MarketType.PERPETUAL,
) -> MarketSnapshot:
    ts = datetime(2026, 3, 17, tzinfo=timezone.utc)
    orderbook = None
    if bid_levels is not None or ask_levels is not None:
        orderbook = OrderBook(
            exchange=exchange,
            symbol=symbol,
            market_type=market_type,
            bids=tuple(
                OrderBookLevel(price=Decimal(price), size=Decimal(size))
                for price, size in (bid_levels or ())
            ),
            asks=tuple(
                OrderBookLevel(price=Decimal(price), size=Decimal(size))
                for price, size in (ask_levels or ())
            ),
            ts=ts,
        )
        if ask_levels:
            top_ask_size = ask_levels[0][1]
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
        orderbook=orderbook,
        liquidity_usd=Decimal(liquidity_usd) if liquidity_usd is not None else None,
        top_ask_size=Decimal(top_ask_size) if top_ask_size is not None else None,
    )
