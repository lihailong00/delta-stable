"""Bybit live runtime wiring."""

from __future__ import annotations

from typing import Any

from arb.exchange.bybit import BybitExchange
from arb.models import MarketType
from arb.net.http import HttpTransport
from arb.runtime.snapshots import SnapshotService
from arb.runtime.streaming import PrivateSessionService, PublicStreamService
from arb.ws.bybit import BybitWebSocketClient


class BybitRuntime:
    """Wire Bybit REST and WS adapters to live transports."""

    def __init__(
        self,
        exchange: BybitExchange,
        public_ws_client: BybitWebSocketClient,
        private_ws_client: BybitWebSocketClient,
        http_transport: HttpTransport,
        snapshot_service: SnapshotService,
        public_stream: PublicStreamService,
        private_session: PrivateSessionService,
        *,
        ws_connector: Any,
    ) -> None:
        self.exchange = exchange
        self.public_ws_client = public_ws_client
        self.private_ws_client = private_ws_client
        self.http_transport = http_transport
        self.snapshot_service = snapshot_service
        self.public_stream = public_stream
        self.private_session = private_session
        self.ws_connector = ws_connector
        self.collector = snapshot_service.collector

    @classmethod
    def build(
        cls,
        *,
        api_key: str,
        api_secret: str,
        market_type: MarketType = MarketType.SPOT,
        recv_window: int = 5000,
        http_transport: HttpTransport,
        ws_connector: Any,
    ) -> "BybitRuntime":
        exchange = BybitExchange(
            api_key,
            api_secret,
            recv_window=recv_window,
            transport=http_transport.request,
        )
        public_ws_client = BybitWebSocketClient(market_type)
        private_ws_client = BybitWebSocketClient(
            market_type,
            api_key=api_key,
            api_secret=api_secret,
            private=True,
        )
        snapshot_service = SnapshotService("bybit", exchange)
        public_stream = PublicStreamService(
            public_ws_client,
            snapshot_service,
            ws_connector=ws_connector,
        )
        private_session = PrivateSessionService(
            private_ws_client.endpoint,
            ws_connector=ws_connector,
        )
        return cls(
            exchange,
            public_ws_client,
            private_ws_client,
            http_transport,
            snapshot_service,
            public_stream,
            private_session,
            ws_connector=ws_connector,
        )

    async def public_ping(self) -> bool:
        await self.http_transport.request(
            {"method": "GET", "url": f"{self.exchange.base_url}/v5/market/time"}
        )
        return True

    async def validate_private_access(self) -> dict[str, Any]:
        balances = await self.exchange.fetch_balances()
        return {key: str(value) for key, value in balances.items()}

    async def fetch_public_snapshot(self, symbol: str, market_type: MarketType) -> dict[str, Any]:
        return await self.snapshot_service.fetch_public_snapshot(symbol, market_type)

    def build_private_auth_message(self, expires: int) -> dict[str, Any]:
        return dict(self.private_ws_client.build_auth_message(expires))

    async def stream_orderbook(self, symbol: str, *, max_messages: int = 1) -> list[dict[str, Any]]:
        return await self.public_stream.stream("orderbook", symbol=symbol, max_messages=max_messages)

    async def stream_ticker(self, symbol: str, *, max_messages: int = 1) -> list[dict[str, Any]]:
        return await self.public_stream.stream("ticker", symbol=symbol, max_messages=max_messages)

    async def auth_private_ws(self, expires: int, *, max_messages: int = 1) -> list[Any]:
        return await self.private_session.run(
            self.private_ws_client.build_auth_message(expires),
            max_messages=max_messages,
        )
