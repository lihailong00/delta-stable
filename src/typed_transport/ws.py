"""WebSocket session wrapper."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol, cast

from .errors import NetworkError, WebSocketClosedError
from .types import JsonValue, serialize_message

try:
    import websockets  # type: ignore
except Exception:  # pragma: no cover
    websockets = None  # type: ignore


class SupportsWebSocket(Protocol):
    async def send(self, message: JsonValue | str) -> None:
        """Send one message."""

    async def recv(self) -> JsonValue | str:
        """Receive one message."""

    async def close(self) -> None:
        """Close the websocket."""


Connector = Callable[[str], Awaitable[SupportsWebSocket]]
SleepFn = Callable[[float], Awaitable[None]]
OnMessage = Callable[[JsonValue | str], Awaitable[None] | None]


class WebSocketSession:
    """Manage a websocket connection with reconnect and subscription restore."""

    def __init__(
        self,
        endpoint: str,
        *,
        connector: Connector | None = None,
        on_message: OnMessage | None = None,
        reconnect_delay: float = 0.1,
        sleep: SleepFn | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.connector = connector or self._default_connector
        self.on_message = on_message
        self.reconnect_delay = reconnect_delay
        self.sleep = sleep or asyncio.sleep
        self.websocket: SupportsWebSocket | None = None
        self.subscriptions: list[object] = []
        self.connected = False

    def add_subscription(self, message: object) -> None:
        self.subscriptions.append(message)

    async def connect(self) -> None:
        self.websocket = await self.connector(self.endpoint)
        self.connected = True
        for message in self.subscriptions:
            await self.websocket.send(serialize_message(message))

    async def send(self, message: object) -> None:
        if self.websocket is None:
            await self.connect()
        assert self.websocket is not None
        await self.websocket.send(serialize_message(message))

    async def receive_once(self) -> JsonValue | str:
        if self.websocket is None:
            await self.connect()
        try:
            assert self.websocket is not None
            message = await self.websocket.recv()
        except Exception as exc:
            self.connected = False
            raise WebSocketClosedError(str(exc)) from exc
        if self.on_message is not None:
            result = self.on_message(message)
            if asyncio.iscoroutine(result):
                await result
        return message

    async def run_forever(self, *, max_messages: int | None = None) -> list[JsonValue | str]:
        messages: list[JsonValue | str] = []
        processed = 0
        while max_messages is None or processed < max_messages:
            try:
                message = await self.receive_once()
                messages.append(message)
                processed += 1
            except WebSocketClosedError:
                await self.sleep(self.reconnect_delay)
                await self.connect()
        return messages

    async def aclose(self) -> None:
        if self.websocket is not None and hasattr(self.websocket, "close"):
            await self.websocket.close()
        self.connected = False

    async def close(self) -> None:
        await self.aclose()

    async def _default_connector(self, endpoint: str) -> SupportsWebSocket:
        if websockets is None:
            raise RuntimeError("websockets is not installed; inject a connector or install websockets")
        try:
            return cast(SupportsWebSocket, await websockets.connect(endpoint))
        except Exception as exc:  # pragma: no cover
            raise NetworkError(str(exc)) from exc
