"""Base WebSocket abstractions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass(slots=True, frozen=True)
class WsEvent:
    exchange: str
    channel: str
    payload: Mapping[str, Any]
    received_at: datetime = field(default_factory=utc_now)


class BaseWebSocketClient(ABC):
    """Shared WS subscription and heartbeat behavior."""

    def __init__(self, exchange: str, endpoint: str, heartbeat_interval: int = 30) -> None:
        self.exchange = exchange
        self.endpoint = endpoint
        self.heartbeat_interval = heartbeat_interval
        self.last_message_at = utc_now()
        self.last_ping_at: datetime | None = None
        self.last_pong_at = self.last_message_at

    @abstractmethod
    def build_subscribe_message(
        self,
        channel: str,
        *,
        symbol: str | None = None,
        market: str | None = None,
    ) -> Mapping[str, Any]:
        """Return the subscription payload for a WS channel."""

    @abstractmethod
    def parse_message(self, message: Mapping[str, Any]) -> list[WsEvent]:
        """Convert a raw WS frame into normalized events."""

    def build_ping_message(self) -> Mapping[str, Any]:
        return {"op": "ping"}

    def is_pong_message(self, message: Mapping[str, Any]) -> bool:
        return message.get("op") == "pong"

    def should_ping(self, now: datetime | None = None) -> bool:
        current = now or utc_now()
        reference = self.last_ping_at or self.last_pong_at
        return current - reference >= timedelta(seconds=self.heartbeat_interval)

    def mark_ping(self, now: datetime | None = None) -> Mapping[str, Any]:
        self.last_ping_at = now or utc_now()
        return self.build_ping_message()

    def mark_pong(self, now: datetime | None = None) -> None:
        current = now or utc_now()
        self.last_pong_at = current
        self.last_message_at = current

    def should_reconnect(self, now: datetime | None = None) -> bool:
        current = now or utc_now()
        timeout = timedelta(seconds=self.heartbeat_interval * 2)
        return current - self.last_pong_at > timeout

    def handle_message(self, message: Mapping[str, Any]) -> list[WsEvent]:
        self.last_message_at = utc_now()
        if self.is_pong_message(message):
            self.mark_pong(self.last_message_at)
            return []
        return self.parse_message(message)
