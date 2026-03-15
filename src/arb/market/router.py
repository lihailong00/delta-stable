"""Simple async event router for normalized market data."""

from __future__ import annotations

import inspect
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

Handler = Callable[[dict[str, Any]], Any]


class EventRouter:
    """Dispatch normalized events by channel."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, channel: str, handler: Handler) -> None:
        self._handlers[channel].append(handler)

    async def publish(self, channel: str, payload: dict[str, Any]) -> None:
        for key in (channel, "*"):
            for handler in self._handlers.get(key, []):
                result = handler(payload)
                if inspect.isawaitable(result):
                    await result
