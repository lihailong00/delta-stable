from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.asyncio

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from typed_transport.ws import WebSocketSession


class _FakeWebSocket:
    def __init__(self, messages: list[object], *, fail_first_recv: bool = False) -> None:
        self.messages = list(messages)
        self.sent: list[object] = []
        self.fail_first_recv = fail_first_recv
        self.recv_calls = 0
        self.closed = False

    async def send(self, message: object) -> None:
        self.sent.append(message)

    async def recv(self) -> object:
        self.recv_calls += 1
        if self.fail_first_recv and self.recv_calls == 1:
            raise RuntimeError("closed")
        return self.messages.pop(0)

    async def close(self) -> None:
        self.closed = True


class _WireMessage:
    def to_dict(self) -> dict[str, object]:
        return {"op": "subscribe", "channel": "ticker"}


class TestTypedWebSocketSession:
    async def test_reconnects_and_restores_subscriptions(self) -> None:
        sockets = [_FakeWebSocket(["ignored"], fail_first_recv=True), _FakeWebSocket(["hello"])]

        async def connector(endpoint: str) -> _FakeWebSocket:
            assert endpoint == "wss://example"
            return sockets.pop(0)

        seen: list[object] = []

        async def on_message(message: object) -> None:
            seen.append(message)

        session = WebSocketSession("wss://example", connector=connector, on_message=on_message)
        session.add_subscription(_WireMessage())

        messages = await session.run_forever(max_messages=1)

        assert messages == ["hello"]
        assert seen == ["hello"]

    async def test_connect_and_send_serialize_messages(self) -> None:
        socket = _FakeWebSocket(["world"])

        async def connector(endpoint: str) -> _FakeWebSocket:
            return socket

        session = WebSocketSession("wss://example", connector=connector)
        session.add_subscription({"op": "subscribe", "channel": "book"})
        await session.connect()
        await session.send({"op": "ping"})
        await session.aclose()

        assert socket.sent == [
            {"op": "subscribe", "channel": "book"},
            {"op": "ping"},
        ]
        assert socket.closed
