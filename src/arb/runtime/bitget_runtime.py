"""Bitget live runtime wiring."""

from __future__ import annotations

from typing import Any

from arb.exchange.bitget import BitgetExchange
from arb.market.collector import MarketDataCollector
from arb.models import MarketType
from arb.net.http import HttpTransport
from arb.net.ws import WebSocketSession
from arb.ws.bitget import BitgetWebSocketClient


class BitgetRuntime:
    """Wire Bitget REST and WS adapters to live transports."""

    def __init__(
        self,
        exchange: BitgetExchange,
        public_ws_client: BitgetWebSocketClient,
        private_ws_client: BitgetWebSocketClient,
        http_transport: HttpTransport,
        *,
        ws_connector: Any,
    ) -> None:
        self.exchange = exchange
        self.public_ws_client = public_ws_client
        self.private_ws_client = private_ws_client
        self.http_transport = http_transport
        self.ws_connector = ws_connector
        self.collector = MarketDataCollector({"bitget": exchange})

    @classmethod
    def build(
        cls,
        *,
        api_key: str,
        api_secret: str,
        passphrase: str,
        market_type: MarketType = MarketType.SPOT,
        product_type: str = "USDT-FUTURES",
        http_transport: HttpTransport,
        ws_connector: Any,
    ) -> "BitgetRuntime":
        exchange = BitgetExchange(
            api_key,
            api_secret,
            passphrase,
            product_type=product_type,
            transport=http_transport.request,
        )
        public_ws_client = BitgetWebSocketClient(market_type)
        private_ws_client = BitgetWebSocketClient(
            market_type,
            api_key=api_key,
            api_secret=api_secret,
            passphrase=passphrase,
            private=True,
        )
        return cls(
            exchange,
            public_ws_client,
            private_ws_client,
            http_transport,
            ws_connector=ws_connector,
        )

    async def public_ping(self) -> bool:
        await self.http_transport.request(
            {"method": "GET", "url": f"{self.exchange.base_url}/api/v2/public/time"}
        )
        return True

    async def validate_private_access(self) -> dict[str, Any]:
        balances = await self.exchange.fetch_balances()
        return {key: str(value) for key, value in balances.items()}

    async def fetch_public_snapshot(self, symbol: str, market_type: MarketType) -> dict[str, Any]:
        return await self.collector.collect_snapshot("bitget", symbol, market_type)

    def build_private_login_message(self, timestamp: str) -> dict[str, Any]:
        return dict(self.private_ws_client.build_login_message(timestamp))

    async def stream_orderbook(self, symbol: str, *, max_messages: int = 1) -> list[dict[str, Any]]:
        return await self._stream_public("books", symbol, max_messages=max_messages)

    async def stream_funding(self, symbol: str, *, max_messages: int = 1) -> list[dict[str, Any]]:
        return await self._stream_public("funding", symbol, max_messages=max_messages)

    async def login_private_ws(self, timestamp: str, *, max_messages: int = 1) -> list[Any]:
        session = WebSocketSession(
            self.private_ws_client.endpoint,
            connector=self.ws_connector,
        )
        session.add_subscription(self.private_ws_client.build_login_message(timestamp))
        return await session.run_forever(max_messages=max_messages)

    async def _stream_public(
        self,
        channel: str,
        symbol: str,
        *,
        max_messages: int,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []

        async def on_message(message: Any) -> None:
            normalized = await self.collector.ingest_ws_message(self.public_ws_client, message)
            events.extend(normalized)

        session = WebSocketSession(
            self.public_ws_client.endpoint,
            connector=self.ws_connector,
            on_message=on_message,
        )
        session.add_subscription(
            self.public_ws_client.build_subscribe_message(channel, symbol=symbol)
        )
        await session.run_forever(max_messages=max_messages)
        return events
