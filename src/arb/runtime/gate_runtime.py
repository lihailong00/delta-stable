"""Gate live runtime wiring."""

from __future__ import annotations

from arb.exchange.gate import GateExchange
from arb.market.schemas import NormalizedWsEvent
from arb.models import MarketType
from arb.net.http import HttpTransport
from arb.net.ws import Connector
from arb.runtime.base_runtime import PublicExchangeRuntime, build_public_runtime_services
from arb.ws.gate import GateWebSocketClient


class GateRuntime(PublicExchangeRuntime):
    """Wire Gate REST and WS adapters to live transports."""

    @classmethod
    def build(
        cls,
        *,
        api_key: str,
        api_secret: str,
        settle: str = "usdt",
        http_transport: HttpTransport,
        ws_connector: Connector,
        ) -> "GateRuntime":
        exchange = GateExchange(
            api_key,
            api_secret,
            settle=settle,
            transport=http_transport.request,
        )
        ws_client = GateWebSocketClient()
        snapshot_service, public_stream = build_public_runtime_services(
            exchange_name="gate",
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
        return await self._ping(f"{self.exchange.base_url}/spot/currency_pairs")

    async def stream_orderbook(self, symbol: str, *, max_messages: int = 1) -> list[NormalizedWsEvent]:
        return await self.stream_public_channel(
            "spot.order_book",
            symbol=symbol,
            max_messages=max_messages,
        )
