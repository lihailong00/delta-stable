"""Market data collector orchestration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from arb.exchange.base import BaseExchangeClient
from arb.market.normalizer import normalize_funding, normalize_orderbook, normalize_ticker, normalize_ws_event
from arb.market.router import EventRouter
from arb.models import MarketType
from arb.ws.base import BaseWebSocketClient


class MarketDataCollector:
    """Collect normalized market data snapshots and WS events."""

    def __init__(
        self,
        exchanges: Mapping[str, BaseExchangeClient],
        *,
        router: EventRouter | None = None,
    ) -> None:
        self.exchanges = dict(exchanges)
        self.router = router or EventRouter()

    async def collect_snapshot(
        self,
        exchange_name: str,
        symbol: str,
        market_type: MarketType,
    ) -> dict[str, Any]:
        exchange = self.exchanges[exchange_name]
        ticker = await exchange.fetch_ticker(symbol, market_type)
        orderbook = await exchange.fetch_orderbook(symbol, market_type)
        snapshot: dict[str, Any] = {
            "ticker": normalize_ticker(ticker),
            "orderbook": normalize_orderbook(orderbook),
        }
        if market_type is MarketType.PERPETUAL:
            funding = await exchange.fetch_funding_rate(symbol)
            snapshot["funding"] = normalize_funding(funding)
        return snapshot

    async def collect_many(
        self,
        requests: list[tuple[str, str, MarketType]],
    ) -> list[dict[str, Any]]:
        snapshots: list[dict[str, Any]] = []
        for exchange_name, symbol, market_type in requests:
            snapshots.append(await self.collect_snapshot(exchange_name, symbol, market_type))
        return snapshots

    async def ingest_ws_message(
        self,
        client: BaseWebSocketClient,
        message: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        normalized_events: list[dict[str, Any]] = []
        for event in client.handle_message(message):
            normalized = normalize_ws_event(event)
            normalized_events.append(normalized)
            await self.router.publish(event.channel, normalized)
        return normalized_events
