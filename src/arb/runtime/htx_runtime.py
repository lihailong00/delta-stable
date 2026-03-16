"""HTX live runtime wiring."""

from __future__ import annotations

from typing import Any

from arb.exchange.htx import HtxExchange
from arb.models import MarketType
from arb.net.http import HttpTransport
from arb.runtime.snapshots import SnapshotService
from arb.runtime.streaming import PublicStreamService
from arb.ws.htx import HtxWebSocketClient


class HtxRuntime:
    """Wire HTX REST and WS adapters to live transports."""

    def __init__(
        self,
        exchange: HtxExchange,
        ws_client: HtxWebSocketClient,
        http_transport: HttpTransport,
        snapshot_service: SnapshotService,
        public_stream: PublicStreamService,
        *,
        ws_connector: Any,
    ) -> None:
        self.exchange = exchange
        self.ws_client = ws_client
        self.http_transport = http_transport
        self.snapshot_service = snapshot_service
        self.public_stream = public_stream
        self.ws_connector = ws_connector
        self.collector = snapshot_service.collector

    @classmethod
    def build(
        cls,
        *,
        api_key: str,
        api_secret: str,
        market_type: MarketType = MarketType.SPOT,
        leverage: int = 5,
        http_transport: HttpTransport,
        ws_connector: Any,
    ) -> "HtxRuntime":
        exchange = HtxExchange(
            api_key,
            api_secret,
            leverage=leverage,
            transport=http_transport.request,
        )
        ws_client = HtxWebSocketClient(market_type)
        snapshot_service = SnapshotService("htx", exchange)
        public_stream = PublicStreamService(
            ws_client,
            snapshot_service,
            ws_connector=ws_connector,
        )
        return cls(
            exchange,
            ws_client,
            http_transport,
            snapshot_service,
            public_stream,
            ws_connector=ws_connector,
        )

    async def public_ping(self) -> bool:
        await self.http_transport.request(
            {"method": "GET", "url": f"{self.exchange.spot_base_url}/v1/common/timestamp"}
        )
        return True

    async def validate_private_access(self) -> dict[str, Any]:
        balances = await self.exchange.fetch_balances()
        return {key: str(value) for key, value in balances.items()}

    async def fetch_public_snapshot(self, symbol: str, market_type: MarketType) -> dict[str, Any]:
        return await self.snapshot_service.fetch_public_snapshot(symbol, market_type)

    async def stream_orderbook(self, symbol: str, *, max_messages: int = 1) -> list[dict[str, Any]]:
        return await self.public_stream.stream("depth", symbol=symbol, max_messages=max_messages)

    async def stream_ticker(self, symbol: str, *, max_messages: int = 1) -> list[dict[str, Any]]:
        return await self.public_stream.stream("ticker", symbol=symbol, max_messages=max_messages)
