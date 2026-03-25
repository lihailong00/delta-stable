from __future__ import annotations

import asyncio

from typed_transport import WebSocketSession


class _Socket:
    def __init__(self, messages: list[object], *, fail_first_recv: bool = False) -> None:
        self.messages = list(messages)
        self.sent: list[object] = []
        self.fail_first_recv = fail_first_recv
        self.recv_calls = 0

    async def send(self, message: object) -> None:
        self.sent.append(message)

    async def recv(self) -> object:
        self.recv_calls += 1
        if self.fail_first_recv and self.recv_calls == 1:
            raise RuntimeError("connection dropped")
        return self.messages.pop(0)

    async def close(self) -> None:
        return None


async def main() -> None:
    sockets = [_Socket(["ignored"], fail_first_recv=True), _Socket(["ticker:update"])]

    async def connector(endpoint: str) -> _Socket:
        assert endpoint == "wss://example.com/ws"
        return sockets.pop(0)

    session = WebSocketSession("wss://example.com/ws", connector=connector)
    session.add_subscription({"op": "subscribe", "channel": "ticker"})
    messages = await session.run_forever(max_messages=1)
    print(messages)
    await session.aclose()


if __name__ == "__main__":
    asyncio.run(main())
