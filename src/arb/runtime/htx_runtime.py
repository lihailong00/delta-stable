"""HTX live runtime wiring."""

from __future__ import annotations

from arb.exchange.htx import HtxExchange
from arb.market.schemas import NormalizedWsEvent
from arb.models import MarketType
from arb.net.http import HttpTransport
from arb.net.ws import Connector
from arb.runtime.base_runtime import PublicExchangeRuntime, build_public_runtime_services
from arb.ws.htx import HtxWebSocketClient


class HtxRuntime(PublicExchangeRuntime):
    """Wire HTX REST and WS adapters to live transports."""

    @classmethod
    def build(
        cls,
        *,
        api_key: str,
        api_secret: str,
        market_type: MarketType = MarketType.SPOT,
        leverage: int = 5,
        http_transport: HttpTransport,
        ws_connector: Connector,
        ) -> "HtxRuntime":
        exchange = HtxExchange(
            api_key,
            api_secret,
            leverage=leverage,
            transport=http_transport.request,
        )
        ws_client = HtxWebSocketClient(market_type)
        snapshot_service, public_stream = build_public_runtime_services(
            exchange_name="htx",
            exchange=exchange,
            ws_client=ws_client,
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
        return await self._ping(f"{self.exchange.spot_base_url}/v1/common/timestamp")

    async def stream_orderbook(self, symbol: str, *, max_messages: int = 1) -> list[NormalizedWsEvent]:
        return await self.stream_public_channel("depth", symbol=symbol, max_messages=max_messages)

    async def stream_ticker(self, symbol: str, *, max_messages: int = 1) -> list[NormalizedWsEvent]:
        return await self.stream_public_channel("ticker", symbol=symbol, max_messages=max_messages)
