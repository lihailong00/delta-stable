"""Binance live runtime wiring."""

from __future__ import annotations

from arb.exchange.binance import BinanceExchange
from arb.market.schemas import NormalizedWsEvent
from arb.models import MarketType
from arb.net.http import HttpTransport
from arb.net.ws import Connector
from arb.runtime.base_runtime import PublicExchangeRuntime, build_public_runtime_services
from arb.ws.binance import BinanceWebSocketClient


class BinanceRuntime(PublicExchangeRuntime):
    """Wire Binance REST and WS adapters to live transports."""

    @classmethod
    def build(
        cls,
        *,
        api_key: str,
        api_secret: str,
        market_type: MarketType = MarketType.SPOT,
        http_transport: HttpTransport,
        ws_connector: Connector,
    ) -> "BinanceRuntime":
        exchange = BinanceExchange(api_key, api_secret, transport=http_transport.request)
        ws_client = BinanceWebSocketClient(market_type)
        snapshot_service, public_stream = build_public_runtime_services(
            exchange_name="binance",
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

    async def public_ping(self, market_type: MarketType = MarketType.SPOT) -> bool:
        path = "/api/v3/ping" if market_type is MarketType.SPOT else "/fapi/v1/ping"
        base = self.exchange.spot_base_url if market_type is MarketType.SPOT else self.exchange.futures_base_url
        return await self._ping(f"{base}{path}")

    async def stream_orderbook(self, symbol: str, *, max_messages: int = 1) -> list[NormalizedWsEvent]:
        return await self.stream_public_channel("depth", symbol=symbol, max_messages=max_messages)
