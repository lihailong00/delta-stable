"""Market data collector orchestration."""

from __future__ import annotations

from collections.abc import Mapping

from arb.exchange.base import BaseExchangeClient
from arb.market.schemas import MarketSnapshot, NormalizedWsEvent
from arb.market.normalizer import normalize_funding, normalize_orderbook, normalize_ticker, normalize_ws_event
from arb.market.spot_perp_view import SpotPerpSnapshot, build_spot_perp_view
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
    ) -> MarketSnapshot:
        exchange = self.exchanges[exchange_name]
        ticker = await exchange.fetch_ticker(symbol, market_type)
        orderbook = await exchange.fetch_orderbook(symbol, market_type)
        top_ask_size = orderbook.asks[0].size if orderbook.asks else None
        liquidity_usd = ticker.ask * top_ask_size if top_ask_size is not None else None
        snapshot = MarketSnapshot(
            ticker=normalize_ticker(ticker),
            orderbook=normalize_orderbook(orderbook),
            top_ask_size=top_ask_size,
            liquidity_usd=liquidity_usd,
        )
        if market_type is MarketType.PERPETUAL:
            funding = await exchange.fetch_funding_rate(symbol)
            snapshot = snapshot.model_copy(update={"funding": normalize_funding(funding)})
        return snapshot

    async def collect_many(
        self,
        requests: list[tuple[str, str, MarketType]],
    ) -> list[MarketSnapshot]:
        snapshots: list[MarketSnapshot] = []
        for exchange_name, symbol, market_type in requests:
            snapshots.append(await self.collect_snapshot(exchange_name, symbol, market_type))
        return snapshots

    async def collect_spot_perp_snapshot(
        self,
        exchange_name: str,
        symbol: str,
        *,
        max_age_seconds: float = 3.0,
    ) -> SpotPerpSnapshot:
        spot_snapshot = await self.collect_snapshot(exchange_name, symbol, MarketType.SPOT)
        perp_snapshot = await self.collect_snapshot(exchange_name, symbol, MarketType.PERPETUAL)
        funding = perp_snapshot.funding
        if funding is None:
            raise ValueError("perpetual snapshot must include funding")
        return SpotPerpSnapshot(
            spot=spot_snapshot,
            perp=perp_snapshot,
            view=build_spot_perp_view(
                exchange=exchange_name,
                symbol=symbol,
                spot_ticker=spot_snapshot.ticker,
                perp_ticker=perp_snapshot.ticker,
                funding=funding,
                max_age_seconds=max_age_seconds,
            ),
        )

    async def ingest_ws_message(
        self,
        client: BaseWebSocketClient,
        message: Mapping[str, object],
    ) -> list[NormalizedWsEvent]:
        normalized_events: list[NormalizedWsEvent] = []
        for event in client.handle_message(message):
            normalized = normalize_ws_event(event)
            normalized_events.append(normalized)
            await self.router.publish(event.channel, normalized)
        return normalized_events
