"""OKX live runtime wiring."""

from __future__ import annotations

from collections.abc import Mapping

from arb.exchange.okx import OkxExchange
from arb.market.schemas import MarketSnapshot, NormalizedWsEvent
from arb.models import MarketType
from arb.net.http import HttpTransport
from arb.net.ws import Connector
from arb.runtime.snapshots import SnapshotService
from arb.runtime.streaming import PrivateSessionService, PublicStreamService
from arb.schemas.base import SerializableValue
from arb.ws.okx import OkxWebSocketClient


class OkxRuntime:
    """Wire OKX REST and WS adapters to live transports."""

    def __init__(
        self,
        exchange: OkxExchange,
        public_ws_client: OkxWebSocketClient,
        private_ws_client: OkxWebSocketClient,
        http_transport: HttpTransport,
        snapshot_service: SnapshotService,
        public_stream: PublicStreamService,
        private_session: PrivateSessionService,
        *,
        ws_connector: Connector,
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
        snapshot_service = SnapshotService("okx", exchange)
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
            {"method": "GET", "url": f"{self.exchange.base_url}/api/v5/public/time"}
        )
        return True

    async def validate_private_access(self) -> dict[str, str]:
        balances = await self.exchange.fetch_balances()
        return {key: str(value) for key, value in balances.items()}

    async def fetch_public_snapshot(self, symbol: str, market_type: MarketType) -> MarketSnapshot:
        return await self.snapshot_service.fetch_public_snapshot(symbol, market_type)

    def build_private_login_message(self, timestamp: str) -> Mapping[str, SerializableValue]:
        return dict(self.private_ws_client.build_login_message(timestamp))

    async def stream_orderbook(self, symbol: str, *, max_messages: int = 1) -> list[NormalizedWsEvent]:
        return await self.public_stream.stream("books", symbol=symbol, max_messages=max_messages)

    async def stream_funding(self, symbol: str, *, max_messages: int = 1) -> list[NormalizedWsEvent]:
        return await self.public_stream.stream("funding-rate", symbol=symbol, max_messages=max_messages)

    async def login_private_ws(
        self,
        timestamp: str,
        *,
        max_messages: int = 1,
    ) -> list[SerializableValue]:
        return await self.private_session.run(
            dict(self.private_ws_client.build_login_message(timestamp)),
            max_messages=max_messages,
        )
