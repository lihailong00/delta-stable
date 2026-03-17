"""Private WS stream helpers for order, fill and position updates."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from arb.execution.private_event_hub import PrivateEventHub
from arb.market.schemas import NormalizedWsEvent
from arb.net.ws import WebSocketSession
from arb.ws.base import BaseWebSocketClient

Connector = Callable[[str], Awaitable[object]]


class PrivateStreamService:
    """Collect normalized private WS events from a subscribable client."""

    def __init__(
        self,
        ws_client: BaseWebSocketClient,
        *,
        ws_connector: Connector,
    ) -> None:
        self.ws_client = ws_client
        self.ws_connector = ws_connector

    async def stream(
        self,
        channel: str,
        *,
        symbol: str | None = None,
        max_messages: int = 1,
        event_hub: PrivateEventHub | None = None,
    ) -> list[NormalizedWsEvent]:
        events: list[NormalizedWsEvent] = []

        async def on_message(message: object) -> None:
            for event in self.ws_client.handle_message(message):
                normalized = NormalizedWsEvent(
                    exchange=event.exchange,
                    channel=event.channel,
                    received_at=event.received_at,
                    payload=dict(event.payload),
                )
                events.append(normalized)
                if event_hub is not None:
                    event_hub.publish(normalized)

        session = WebSocketSession(
            self.ws_client.endpoint,
            connector=self.ws_connector,
            on_message=on_message,
        )
        session.add_subscription(self.ws_client.build_subscribe_message(channel, symbol=symbol))
        await session.run_forever(max_messages=max_messages)
        return events
