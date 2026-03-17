"""Private websocket event fan-in for execution and reconciliation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timezone

from pydantic import Field

from arb.market.schemas import NormalizedWsEvent
from arb.schemas.base import ArbFrozenModel, SerializableValue


class OrderUpdatePayload(ArbFrozenModel):
    exchange: str | None = None
    symbol: str
    order_id: str
    status: str | None = None
    side: str | None = None
    quantity: str | None = None
    filled_quantity: str | None = None
    raw: dict[str, SerializableValue] = Field(default_factory=dict)


class FillUpdatePayload(ArbFrozenModel):
    exchange: str | None = None
    symbol: str
    order_id: str
    fill_id: str
    side: str | None = None
    quantity: str | None = None
    price: str | None = None
    raw: dict[str, SerializableValue] = Field(default_factory=dict)


class PositionUpdatePayload(ArbFrozenModel):
    exchange: str | None = None
    symbol: str
    quantity: str | None = None
    direction: str | None = None
    raw: dict[str, SerializableValue] = Field(default_factory=dict)


class PrivateEventHub:
    """Buffer normalized private events keyed by order and symbol."""

    def __init__(self) -> None:
        self._orders: dict[str, list[OrderUpdatePayload]] = defaultdict(list)
        self._fills: dict[str, list[FillUpdatePayload]] = defaultdict(list)
        self._positions: dict[str, list[PositionUpdatePayload]] = defaultdict(list)

    def publish(self, event: NormalizedWsEvent | dict[str, object]) -> None:
        if isinstance(event, NormalizedWsEvent):
            normalized = event
        else:
            payload = dict(event.get("payload", {})) if isinstance(event.get("payload"), dict) else {}
            normalized = NormalizedWsEvent.model_validate(
                {
                    "exchange": event.get("exchange", payload.get("exchange", "")),
                    "channel": event.get("channel", ""),
                    "payload": payload,
                    "received_at": event.get("received_at", datetime.now(tz=timezone.utc)),
                }
            )
        payload = dict(normalized.payload)
        if normalized.exchange and "exchange" not in payload:
            payload["exchange"] = normalized.exchange

        if normalized.channel == "order.update" and payload.get("order_id") is not None:
            order_payload = OrderUpdatePayload.model_validate(
                {
                    "exchange": payload.get("exchange"),
                    "symbol": payload["symbol"],
                    "order_id": payload["order_id"],
                    "status": payload.get("status"),
                    "side": payload.get("side"),
                    "quantity": payload.get("quantity"),
                    "filled_quantity": payload.get("filled_quantity"),
                    "raw": payload,
                }
            )
            self._orders[order_payload.order_id].append(order_payload)
        elif normalized.channel == "fill.update" and payload.get("order_id") is not None:
            fill_payload = FillUpdatePayload.model_validate(
                {
                    "exchange": payload.get("exchange"),
                    "symbol": payload["symbol"],
                    "order_id": payload["order_id"],
                    "fill_id": payload["fill_id"],
                    "side": payload.get("side"),
                    "quantity": payload.get("quantity"),
                    "price": payload.get("price"),
                    "raw": payload,
                }
            )
            self._fills[fill_payload.order_id].append(fill_payload)
        elif normalized.channel == "position.update" and payload.get("symbol") is not None:
            position_payload = PositionUpdatePayload.model_validate(
                {
                    "exchange": payload.get("exchange"),
                    "symbol": payload["symbol"],
                    "quantity": payload.get("quantity"),
                    "direction": payload.get("direction"),
                    "raw": payload,
                }
            )
            self._positions[position_payload.symbol].append(position_payload)

    def publish_many(self, events: Iterable[NormalizedWsEvent | dict[str, object]]) -> None:
        for event in events:
            self.publish(event)

    def pop_order(self, order_id: str) -> OrderUpdatePayload | None:
        queue = self._orders.get(order_id)
        if not queue:
            return None
        payload = queue.pop(0)
        if not queue:
            self._orders.pop(order_id, None)
        return payload

    def drain_fills(self, order_id: str) -> list[FillUpdatePayload]:
        return self._fills.pop(order_id, [])

    def latest_position(self, symbol: str) -> PositionUpdatePayload | None:
        queue = self._positions.get(symbol)
        if not queue:
            return None
        return queue[-1]
