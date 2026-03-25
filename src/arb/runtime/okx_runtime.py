"""OKX live runtime wiring."""

from __future__ import annotations

from collections.abc import Mapping

from arb.exchange.okx import OkxExchange
from arb.market.schemas import NormalizedWsEvent
from arb.models import MarketType
from arb.net.http import HttpTransport
from arb.net.ws import Connector
from arb.runtime.base_runtime import PrivateExchangeRuntime, build_private_runtime_services
from arb.schemas.base import SerializableValue
from arb.ws.okx import OkxWebSocketClient


class OkxRuntime(PrivateExchangeRuntime):
    """Wire OKX REST and WS adapters to live transports."""

    @classmethod
    def build(
        cls,
        *,
        api_key: str,
        api_secret: str,
        passphrase: str,
        market_type: MarketType = MarketType.SPOT,
        http_transport: HttpTransport,
        ws_connector: Connector,
    ) -> "OkxRuntime":
        exchange = OkxExchange(
            api_key,
            api_secret,
            passphrase,
            transport=http_transport.request,
        )
        public_ws_client = OkxWebSocketClient(market_type)
        private_ws_client = OkxWebSocketClient(
            market_type,
            api_key=api_key,
            api_secret=api_secret,
            passphrase=passphrase,
            private=True,
        )
        snapshot_service, public_stream, private_session = build_private_runtime_services(
            exchange_name="okx",
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
        return await self._ping(f"{self.exchange.base_url}/api/v5/public/time")

    def build_private_login_message(self, timestamp: str) -> Mapping[str, SerializableValue]:
        return dict(self.private_ws_client.build_login_message(timestamp))

    async def stream_orderbook(self, symbol: str, *, max_messages: int = 1) -> list[NormalizedWsEvent]:
        return await self.stream_public_channel("books", symbol=symbol, max_messages=max_messages)

    async def stream_funding(self, symbol: str, *, max_messages: int = 1) -> list[NormalizedWsEvent]:
        return await self.stream_public_channel("funding-rate", symbol=symbol, max_messages=max_messages)

    async def login_private_ws(
        self,
        timestamp: str,
        *,
        max_messages: int = 1,
    ) -> list[SerializableValue]:
        return await self.run_private_session(
            self.private_ws_client.build_login_message(timestamp),
            max_messages=max_messages,
        )
