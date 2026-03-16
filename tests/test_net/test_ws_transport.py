from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.net.ws import WebSocketSession


class _FakeWebSocket:
    def __init__(self, messages, *, fail_first_recv: bool = False) -> None:
        self.messages = list(messages)
        self.sent = []
        self.fail_first_recv = fail_first_recv
        self.recv_calls = 0

    async def send(self, message) -> None:
        self.sent.append(message)

    async def recv(self):
        self.recv_calls += 1
        if self.fail_first_recv and self.recv_calls == 1:
            raise RuntimeError("closed")
        return self.messages.pop(0)

    async def close(self) -> None:
        return None


class WebSocketSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_reconnects_and_restores_subscriptions(self) -> None:
        sockets = [
            _FakeWebSocket(["ignored"], fail_first_recv=True),
            _FakeWebSocket(["hello"]),
        ]

        async def connector(endpoint: str):
            return sockets.pop(0)

        seen = []

        async def on_message(message):
            seen.append(message)

        session = WebSocketSession("wss://example", connector=connector, on_message=on_message)
        session.add_subscription({"op": "subscribe", "channel": "ticker"})
        messages = await session.run_forever(max_messages=1)

        self.assertEqual(messages, ["hello"])
        self.assertEqual(seen, ["hello"])
        self.assertEqual(sockets, [])

    async def test_initial_connect_restores_subscriptions(self) -> None:
        socket = _FakeWebSocket(["world"])

        async def connector(endpoint: str):
            return socket

        session = WebSocketSession("wss://example", connector=connector)
        session.add_subscription({"op": "subscribe", "channel": "book"})
        await session.connect()
        self.assertEqual(socket.sent, [{"op": "subscribe", "channel": "book"}])


if __name__ == "__main__":
    unittest.main()
