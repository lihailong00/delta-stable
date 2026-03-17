"""Snapshot composition helpers used by live runtimes."""

from __future__ import annotations

from collections.abc import Mapping

from arb.exchange.base import BaseExchangeClient
from arb.market.collector import MarketDataCollector
from arb.market.schemas import MarketSnapshot, NormalizedWsEvent
from arb.market.spot_perp_view import SpotPerpSnapshot
from arb.models import MarketType
from arb.ws.base import BaseWebSocketClient


class SnapshotService:
    """Compose market snapshot collection and WS normalization for one exchange."""

    def __init__(self, exchange_name: str, exchange: BaseExchangeClient) -> None:
        self.exchange_name = exchange_name
        self.exchange = exchange
        self.collector = MarketDataCollector({exchange_name: exchange})

    async def fetch_public_snapshot(
        self,
        symbol: str,
        market_type: MarketType,
    ) -> MarketSnapshot:
        return await self.collector.collect_snapshot(self.exchange_name, symbol, market_type)

    async def fetch_spot_perp_snapshot(
        self,
        symbol: str,
        *,
        max_age_seconds: float = 3.0,
    ) -> SpotPerpSnapshot:
        return await self.collector.collect_spot_perp_snapshot(
            self.exchange_name,
            symbol,
            max_age_seconds=max_age_seconds,
        )

    async def ingest_ws_message(
        self,
        client: BaseWebSocketClient,
        message: Mapping[str, object],
    ) -> list[NormalizedWsEvent]:
        return await self.collector.ingest_ws_message(client, message)
