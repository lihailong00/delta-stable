"""Private websocket event fan-in for execution and reconciliation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any


class PrivateEventHub:
    """Buffer normalized private events keyed by order and symbol."""

    def __init__(self) -> None:
        self._orders: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._fills: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._positions: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def publish(self, event: dict[str, Any]) -> None:
        channel = str(event.get("channel", ""))
        payload = dict(event.get("payload", {}))
        if event.get("exchange") is not None and "exchange" not in payload:
            payload["exchange"] = event["exchange"]
        if channel == "order.update" and payload.get("order_id") is not None:
            self._orders[str(payload["order_id"])].append(payload)
        elif channel == "fill.update" and payload.get("order_id") is not None:
            self._fills[str(payload["order_id"])].append(payload)
        elif channel == "position.update" and payload.get("symbol") is not None:
            self._positions[str(payload["symbol"])].append(payload)

    def publish_many(self, events: Iterable[dict[str, Any]]) -> None:
        for event in events:
            self.publish(event)

    def pop_order(self, order_id: str) -> dict[str, Any] | None:
        queue = self._orders.get(order_id)
        if not queue:
            return None
        payload = queue.pop(0)
        if not queue:
            self._orders.pop(order_id, None)
        return payload

    def drain_fills(self, order_id: str) -> list[dict[str, Any]]:
        return self._fills.pop(order_id, [])

    def latest_position(self, symbol: str) -> dict[str, Any] | None:
        queue = self._positions.get(symbol)
        if not queue:
            return None
        return queue[-1]
