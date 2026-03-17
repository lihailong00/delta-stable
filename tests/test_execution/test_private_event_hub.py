from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.execution.private_event_hub import PrivateEventHub
from arb.runtime.private_streams import PrivateStreamService
from arb.ws.base import BaseWebSocketClient, WsEvent


class _DummyWsClient(BaseWebSocketClient):
    def __init__(self) -> None:
        super().__init__("dummy", "wss://example.test/ws")

    def build_subscribe_message(self, channel: str, *, symbol: str | None = None, market: str | None = None):
        return {"op": "subscribe", "channel": channel, "symbol": symbol}

    def parse_message(self, message):
        return [
            WsEvent(
                exchange=self.exchange,
                channel="order.update",
                payload={
                    "symbol": "BTC/USDT",
                    "order_id": "ord-1",
                    "status": "filled",
                    "side": "buy",
                    "quantity": "1",
                    "filled_quantity": "1",
                },
            ),
            WsEvent(
                exchange=self.exchange,
                channel="fill.update",
                payload={
                    "symbol": "BTC/USDT",
                    "order_id": "ord-1",
                    "fill_id": "fill-1",
                    "side": "buy",
                    "quantity": "1",
                    "price": "100",
                },
            ),
        ]


class _WebSocket:
    def __init__(self, messages):
        self.messages = list(messages)
        self.sent = []

    async def send(self, message):
        self.sent.append(message)

    async def recv(self):
        return self.messages.pop(0)

    async def close(self):
        return None


@pytest.mark.asyncio
class TestPrivateEventHub:
    async def test_private_stream_service_publishes_events_into_hub(self) -> None:
        socket = _WebSocket([{"value": "payload"}])

        async def connector(endpoint: str):
            assert endpoint == "wss://example.test/ws"
            return socket

        hub = PrivateEventHub()
        service = PrivateStreamService(_DummyWsClient(), ws_connector=connector)
        events = await service.stream("orders", event_hub=hub)
        assert len(events) == 2
        assert hub.pop_order("ord-1")["status"] == "filled"
        assert hub.drain_fills("ord-1")[0]["fill_id"] == "fill-1"
