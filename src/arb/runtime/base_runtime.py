"""Shared helpers for exchange runtime wiring."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from arb.market.schemas import MarketSnapshot, NormalizedWsEvent
from arb.market.spot_perp_view import SpotPerpSnapshot
from arb.models import MarketType
from arb.net.http import HttpTransport
from arb.net.ws import Connector
from arb.runtime.snapshots import SnapshotService
from arb.runtime.streaming import PrivateSessionService, PublicStreamService
from arb.schemas.base import SerializableValue
from arb.ws.base import BaseWebSocketClient


class SupportsBalanceExchange(Protocol):
    async def fetch_balances(self) -> Mapping[object, object]:
        """Return exchange balances keyed by asset or symbol."""


class ExchangeRuntimeBase:
    """Common runtime surface shared by all exchange adapters."""

    def __init__(
        self,
        exchange: SupportsBalanceExchange,
        http_transport: HttpTransport,
        snapshot_service: SnapshotService,
        *,
        ws_connector: Connector,
    ) -> None:
        self.exchange = exchange
        self.http_transport = http_transport
        self.snapshot_service = snapshot_service
        self.ws_connector = ws_connector
        self.collector = snapshot_service.collector

    async def _ping(self, url: str) -> bool:
        await self.http_transport.request({"method": "GET", "url": url})
        return True

    async def validate_private_access(self) -> dict[str, str]:
        balances = await self.exchange.fetch_balances()
        return {str(key): str(value) for key, value in balances.items()}

    async def fetch_public_snapshot(self, symbol: str, market_type: MarketType) -> MarketSnapshot:
        return await self.snapshot_service.fetch_public_snapshot(symbol, market_type)

    async def fetch_spot_perp_snapshot(
        self,
        symbol: str,
        *,
        max_age_seconds: float = 3.0,
    ) -> SpotPerpSnapshot:
        return await self.snapshot_service.fetch_spot_perp_snapshot(symbol, max_age_seconds=max_age_seconds)


class PublicExchangeRuntime(ExchangeRuntimeBase):
    """Runtime base for exchanges that only need one public websocket client."""

    def __init__(
        self,
        exchange: SupportsBalanceExchange,
        ws_client: BaseWebSocketClient,
        http_transport: HttpTransport,
        snapshot_service: SnapshotService,
        public_stream: PublicStreamService,
        *,
        ws_connector: Connector,
    ) -> None:
        super().__init__(
            exchange,
            http_transport,
            snapshot_service,
            ws_connector=ws_connector,
        )
        self.ws_client = ws_client
        self.public_stream = public_stream

    @property
    def orderbook_stream(self) -> PublicStreamService:
        return self.public_stream

    async def stream_public_channel(
        self,
        channel: str,
        *,
        symbol: str,
        max_messages: int = 1,
    ) -> list[NormalizedWsEvent]:
        return await self.public_stream.stream(channel, symbol=symbol, max_messages=max_messages)


class PrivateExchangeRuntime(ExchangeRuntimeBase):
    """Runtime base for exchanges with separate public/private websocket flows."""

    def __init__(
        self,
        exchange: SupportsBalanceExchange,
        public_ws_client: BaseWebSocketClient,
        private_ws_client: BaseWebSocketClient,
        http_transport: HttpTransport,
        snapshot_service: SnapshotService,
        public_stream: PublicStreamService,
        private_session: PrivateSessionService,
        *,
        ws_connector: Connector,
    ) -> None:
        super().__init__(
            exchange,
            http_transport,
            snapshot_service,
            ws_connector=ws_connector,
        )
        self.public_ws_client = public_ws_client
        self.private_ws_client = private_ws_client
        self.public_stream = public_stream
        self.private_session = private_session

    async def stream_public_channel(
        self,
        channel: str,
        *,
        symbol: str,
        max_messages: int = 1,
    ) -> list[NormalizedWsEvent]:
        return await self.public_stream.stream(channel, symbol=symbol, max_messages=max_messages)

    async def run_private_session(
        self,
        message: Mapping[str, SerializableValue],
        *,
        max_messages: int = 1,
    ) -> list[SerializableValue]:
        return await self.private_session.run(dict(message), max_messages=max_messages)


def build_public_runtime_services(
    *,
    exchange_name: str,
    exchange: object,
    ws_client: BaseWebSocketClient,
    ws_connector: Connector,
) -> tuple[SnapshotService, PublicStreamService]:
    """Create shared snapshot and public-stream services for one exchange."""

    snapshot_service = SnapshotService(exchange_name, exchange)
    public_stream = PublicStreamService(
        ws_client,
        snapshot_service,
        ws_connector=ws_connector,
    )
    return snapshot_service, public_stream


def build_private_runtime_services(
    *,
    exchange_name: str,
    exchange: object,
    public_ws_client: BaseWebSocketClient,
    private_ws_client: BaseWebSocketClient,
    ws_connector: Connector,
) -> tuple[SnapshotService, PublicStreamService, PrivateSessionService]:
    """Create shared snapshot, public-stream and private-session services."""

    snapshot_service, public_stream = build_public_runtime_services(
        exchange_name=exchange_name,
        exchange=exchange,
        ws_client=public_ws_client,
        ws_connector=ws_connector,
    )
    private_session = PrivateSessionService(
        private_ws_client.endpoint,
        ws_connector=ws_connector,
    )
    return snapshot_service, public_stream, private_session
