"""HTX live runtime wiring."""

from __future__ import annotations

from typing import Any

from arb.exchange.htx import HtxExchange
from arb.market.collector import MarketDataCollector
from arb.models import MarketType
from arb.net.http import HttpTransport
from arb.net.ws import WebSocketSession
from arb.ws.htx import HtxWebSocketClient


class HtxRuntime:
    """Wire HTX REST and WS adapters to live transports."""

    def __init__(
        self,
        exchange: HtxExchange,
        ws_client: HtxWebSocketClient,
        http_transport: HttpTransport,
        *,
        ws_connector: Any,
    ) -> None:
        self.exchange = exchange
        self.ws_client = ws_client
        self.http_transport = http_transport
        self.ws_connector = ws_connector
        self.collector = MarketDataCollector({"htx": exchange})

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
        return cls(exchange, ws_client, http_transport, ws_connector=ws_connector)

    async def public_ping(self) -> bool:
        await self.http_transport.request(
            {"method": "GET", "url": f"{self.exchange.spot_base_url}/v1/common/timestamp"}
        )
        return True

    async def validate_private_access(self) -> dict[str, Any]:
        balances = await self.exchange.fetch_balances()
        return {key: str(value) for key, value in balances.items()}

    async def fetch_public_snapshot(self, symbol: str, market_type: MarketType) -> dict[str, Any]:
        return await self.collector.collect_snapshot("htx", symbol, market_type)

    async def stream_orderbook(self, symbol: str, *, max_messages: int = 1) -> list[dict[str, Any]]:
        return await self._stream_public("depth", symbol, max_messages=max_messages)

    async def stream_ticker(self, symbol: str, *, max_messages: int = 1) -> list[dict[str, Any]]:
        return await self._stream_public("ticker", symbol, max_messages=max_messages)

    async def _stream_public(
        self,
        channel: str,
        symbol: str,
        *,
        max_messages: int,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []

        async def on_message(message: Any) -> None:
            normalized = await self.collector.ingest_ws_message(self.ws_client, message)
            events.extend(normalized)

        session = WebSocketSession(
            self.ws_client.endpoint,
            connector=self.ws_connector,
            on_message=on_message,
        )
        session.add_subscription(self.ws_client.build_subscribe_message(channel, symbol=symbol))
        await session.run_forever(max_messages=max_messages)
        return events
