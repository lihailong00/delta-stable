"""Composable WS helpers shared by live runtimes."""

from __future__ import annotations

from collections.abc import Mapping

from arb.market.schemas import NormalizedWsEvent
from arb.net.ws import Connector, WebSocketSession
from arb.runtime.snapshots import SnapshotService
from arb.schemas.base import SerializableValue
from arb.ws.base import BaseWebSocketClient


class PublicStreamService:
    """Collect normalized events from a public WS subscription."""

    def __init__(
        self,
        ws_client: BaseWebSocketClient,
        snapshot_service: SnapshotService,
        *,
        ws_connector: Connector,
    ) -> None:
        self.ws_client = ws_client
        self.snapshot_service = snapshot_service
        self.ws_connector = ws_connector

    async def stream(
        self,
        channel: str,
        *,
        symbol: str,
        max_messages: int = 1,
    ) -> list[NormalizedWsEvent]:
        events: list[NormalizedWsEvent] = []

        async def on_message(message: object) -> None:
            normalized = await self.snapshot_service.ingest_ws_message(self.ws_client, message)
            events.extend(normalized)

        session = WebSocketSession(
            self.ws_client.endpoint,
            connector=self.ws_connector,
            on_message=on_message,
        )
        session.add_subscription(self.ws_client.build_subscribe_message(channel, symbol=symbol))
        await session.run_forever(max_messages=max_messages)
        return events


class PrivateSessionService:
    """Run a one-shot private WS session such as login/auth."""

    def __init__(
        self,
        endpoint: str,
        *,
        ws_connector: Connector,
    ) -> None:
        self.endpoint = endpoint
        self.ws_connector = ws_connector

    async def run(
        self,
        message: Mapping[str, SerializableValue],
        *,
        max_messages: int = 1,
    ) -> list[SerializableValue]:
        session = WebSocketSession(
            self.endpoint,
            connector=self.ws_connector,
        )
        session.add_subscription(message)
        return await session.run_forever(max_messages=max_messages)
