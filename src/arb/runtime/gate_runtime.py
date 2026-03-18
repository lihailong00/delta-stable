"""Gate live runtime wiring."""

from __future__ import annotations

from arb.exchange.gate import GateExchange
from arb.market.schemas import MarketSnapshot, NormalizedWsEvent
from arb.models import MarketType
from arb.net.http import HttpTransport
from arb.net.ws import Connector
from arb.runtime.snapshots import SnapshotService
from arb.runtime.streaming import PublicStreamService
from arb.ws.gate import GateWebSocketClient


class GateRuntime:
    """Wire Gate REST and WS adapters to live transports."""

    def __init__(
        self,
        exchange: GateExchange,
        ws_client: GateWebSocketClient,
        http_transport: HttpTransport,
        snapshot_service: SnapshotService,
        orderbook_stream: PublicStreamService,
        *,
        ws_connector: Connector,
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
        snapshot_service = SnapshotService("gate", exchange)
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

    async def public_ping(self) -> bool:
        await self.http_transport.request(
            {"method": "GET", "url": f"{self.exchange.base_url}/spot/currency_pairs"}
        )
        return True

    async def validate_private_access(self) -> dict[str, str]:
        balances = await self.exchange.fetch_balances()
        return {key: str(value) for key, value in balances.items()}

    async def fetch_public_snapshot(self, symbol: str, market_type: MarketType) -> MarketSnapshot:
        return await self.snapshot_service.fetch_public_snapshot(symbol, market_type)

    async def stream_orderbook(self, symbol: str, *, max_messages: int = 1) -> list[NormalizedWsEvent]:
        return await self.orderbook_stream.stream(
            "spot.order_book",
            symbol=symbol,
            max_messages=max_messages,
        )
