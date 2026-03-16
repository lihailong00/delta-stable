"""Binance live runtime wiring."""

from __future__ import annotations

from typing import Any

from arb.exchange.binance import BinanceExchange
from arb.models import MarketType
from arb.net.http import HttpTransport
from arb.runtime.snapshots import SnapshotService
from arb.runtime.streaming import PublicStreamService
from arb.ws.binance import BinanceWebSocketClient


class BinanceRuntime:
    """Wire Binance REST and WS adapters to live transports."""

    def __init__(
        self,
        exchange: BinanceExchange,
        ws_client: BinanceWebSocketClient,
        http_transport: HttpTransport,
        snapshot_service: SnapshotService,
        orderbook_stream: PublicStreamService,
        *,
        ws_connector: Any,
    ) -> None:
        self.exchange = exchange
        self.ws_client = ws_client
        self.http_transport = http_transport
        self.snapshot_service = snapshot_service
        self.orderbook_stream = orderbook_stream
        self.ws_connector = ws_connector
        self.collector = snapshot_service.collector

    @classmethod
    def build(
        cls,
        *,
        api_key: str,
        api_secret: str,
        market_type: MarketType = MarketType.SPOT,
        http_transport: HttpTransport,
        ws_connector: Any,
    ) -> "BinanceRuntime":
        exchange = BinanceExchange(api_key, api_secret, transport=http_transport.request)
        ws_client = BinanceWebSocketClient(market_type)
        snapshot_service = SnapshotService("binance", exchange)
        orderbook_stream = PublicStreamService(
            ws_client,
            snapshot_service,
            ws_connector=ws_connector,
        )
        return cls(
            exchange,
            ws_client,
            http_transport,
            snapshot_service,
            orderbook_stream,
            ws_connector=ws_connector,
        )

    async def public_ping(self, market_type: MarketType = MarketType.SPOT) -> bool:
        path = "/api/v3/ping" if market_type is MarketType.SPOT else "/fapi/v1/ping"
        base = self.exchange.spot_base_url if market_type is MarketType.SPOT else self.exchange.futures_base_url
        await self.http_transport.request({"method": "GET", "url": f"{base}{path}"})
        return True

    async def validate_private_access(self) -> dict[str, Any]:
        balances = await self.exchange.fetch_balances()
        return {key: str(value) for key, value in balances.items()}

    async def fetch_public_snapshot(self, symbol: str, market_type: MarketType) -> dict[str, Any]:
        return await self.snapshot_service.fetch_public_snapshot(symbol, market_type)

    async def stream_orderbook(self, symbol: str, *, max_messages: int = 1) -> list[dict[str, Any]]:
        return await self.orderbook_stream.stream("depth", symbol=symbol, max_messages=max_messages)
