"""Bybit live runtime wiring."""

from __future__ import annotations

from collections.abc import Mapping

from arb.exchange.bybit import BybitExchange
from arb.market.schemas import NormalizedWsEvent
from arb.models import MarketType
from arb.net.http import HttpTransport
from arb.net.ws import Connector
from arb.runtime.base_runtime import PrivateExchangeRuntime, build_private_runtime_services
from arb.schemas.base import SerializableValue
from arb.ws.bybit import BybitWebSocketClient


class BybitRuntime(PrivateExchangeRuntime):
    """Wire Bybit REST and WS adapters to live transports."""

    @classmethod
    def build(
        cls,
        *,
        api_key: str,
        api_secret: str,
        market_type: MarketType = MarketType.SPOT,
        recv_window: int = 5000,
        http_transport: HttpTransport,
        ws_connector: Connector,
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
        snapshot_service, public_stream, private_session = build_private_runtime_services(
            exchange_name="bybit",
            exchange=exchange,
            public_ws_client=public_ws_client,
            private_ws_client=private_ws_client,
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
        return await self._ping(f"{self.exchange.base_url}/v5/market/time")

    def build_private_auth_message(self, expires: int) -> Mapping[str, SerializableValue]:
        return dict(self.private_ws_client.build_auth_message(expires))

    async def stream_orderbook(self, symbol: str, *, max_messages: int = 1) -> list[NormalizedWsEvent]:
        return await self.stream_public_channel("orderbook", symbol=symbol, max_messages=max_messages)

    async def stream_ticker(self, symbol: str, *, max_messages: int = 1) -> list[NormalizedWsEvent]:
        return await self.stream_public_channel("ticker", symbol=symbol, max_messages=max_messages)

    async def auth_private_ws(
        self,
        expires: int,
        *,
        max_messages: int = 1,
    ) -> list[SerializableValue]:
        return await self.run_private_session(
            self.private_ws_client.build_auth_message(expires),
            max_messages=max_messages,
        )
