"""Order lifecycle tracking helpers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from arb.execution.private_event_hub import PrivateEventHub
from arb.models import Fill, MarketType, Order, OrderStatus
from arb.models import Side

TERMINAL_STATUSES = {
    OrderStatus.FILLED,
    OrderStatus.CANCELED,
    OrderStatus.REJECTED,
    OrderStatus.EXPIRED,
}


@dataclass(slots=True)
class OrderTrackResult:
    initial_order: Order
    final_order: Order
    fills: list[Fill] = field(default_factory=list)
    polls: int = 0
    timed_out: bool = False
    canceled: bool = False

    @property
    def partially_filled(self) -> bool:
        return self.final_order.filled_quantity > 0 and self.final_order.remaining_quantity > 0


class OrderTracker:
    """Track submitted orders until they settle or time out."""

    def __init__(
        self,
        *,
        max_polls: int = 5,
        poll_interval: float = 0.05,
        sleep: Any | None = None,
        event_hub: PrivateEventHub | None = None,
    ) -> None:
        self.max_polls = max_polls
        self.poll_interval = poll_interval
        self.sleep = sleep or asyncio.sleep
        self.event_hub = event_hub

    async def track_order(
        self,
        client: Any,
        order: Order,
        *,
        symbol: str,
        market_type: MarketType,
    ) -> OrderTrackResult:
        if not hasattr(client, "fetch_order"):
            fills = await self._fetch_fills(client, order.order_id, symbol, market_type)
            return OrderTrackResult(initial_order=order, final_order=order, fills=fills)

        current = order
        polls = 0
        while polls < self.max_polls:
            current = await self._next_order_state(client, current, symbol, market_type)
            polls += 1
            if self._is_terminal(current):
                fills = await self._fetch_fills(client, current.order_id, symbol, market_type)
                return OrderTrackResult(initial_order=order, final_order=current, fills=fills, polls=polls)
            await self._sleep(self.poll_interval)

        canceled = False
        if hasattr(client, "cancel_order") and order.order_id is not None:
            canceled_order = await client.cancel_order(str(order.order_id), symbol, market_type)
            if canceled_order is not None:
                current = self._merge_cancel(current, canceled_order)
            canceled = True
        fills = await self._fetch_fills(client, current.order_id, symbol, market_type)
        return OrderTrackResult(
            initial_order=order,
            final_order=current,
            fills=fills,
            polls=polls,
            timed_out=True,
            canceled=canceled,
        )

    def _is_terminal(self, order: Order) -> bool:
        return order.status in TERMINAL_STATUSES or (
            order.filled_quantity >= order.quantity and order.quantity > 0
        )

    async def _fetch_fills(
        self,
        client: Any,
        order_id: str | None,
        symbol: str,
        market_type: MarketType,
    ) -> list[Fill]:
        if order_id is None or not hasattr(client, "fetch_fills"):
            return self._event_fills(order_id, symbol, market_type)
        fills = list(await client.fetch_fills(str(order_id), symbol, market_type))
        event_fills = self._event_fills(order_id, symbol, market_type)
        merged: dict[str, Fill] = {fill.fill_id: fill for fill in fills}
        for fill in event_fills:
            merged.setdefault(fill.fill_id, fill)
        return list(merged.values())

    async def _sleep(self, delay: float) -> None:
        result = self.sleep(delay)
        if asyncio.iscoroutine(result):
            await result

    async def _next_order_state(
        self,
        client: Any,
        current: Order,
        symbol: str,
        market_type: MarketType,
    ) -> Order:
        if self.event_hub is not None and current.order_id is not None:
            payload = self.event_hub.pop_order(str(current.order_id))
            if payload is not None:
                return self._merge_order(current, self._order_from_event(current, payload, market_type))
        return self._merge_order(current, await client.fetch_order(str(current.order_id), symbol, market_type))

    def _event_fills(
        self,
        order_id: str | None,
        symbol: str,
        market_type: MarketType,
    ) -> list[Fill]:
        if self.event_hub is None or order_id is None:
            return []
        events = self.event_hub.drain_fills(order_id)
        fills: list[Fill] = []
        for payload in events:
            fills.append(
                Fill(
                    exchange=str(payload.get("exchange", "")) or str(payload.get("venue", "")) or "",
                    symbol=str(payload.get("symbol", symbol)),
                    market_type=market_type,
                    order_id=str(payload.get("order_id", order_id)),
                    fill_id=str(payload.get("fill_id", "")),
                    side=Side(str(payload.get("side", "buy")).lower()),
                    quantity=payload_decimal(payload.get("quantity", "0")),
                    price=payload_decimal(payload.get("price", "0")),
                    fee=payload_decimal(payload.get("fee", "0")),
                    fee_asset=payload.get("fee_asset"),
                )
            )
        return fills

    def _order_from_event(
        self,
        current: Order,
        payload: dict[str, Any],
        market_type: MarketType,
    ) -> Order:
        return Order(
            exchange=str(payload.get("exchange", current.exchange)) or current.exchange,
            symbol=str(payload.get("symbol", current.symbol)) or current.symbol,
            market_type=market_type,
            side=Side(str(payload.get("side", current.side.value)).lower()),
            quantity=payload_decimal(payload.get("quantity", current.quantity)),
            price=(
                payload_decimal(payload["price"])
                if payload.get("price") not in (None, "")
                else current.price
            ),
            status=self._normalize_status(str(payload.get("status", current.status.value))),
            order_id=str(payload.get("order_id", current.order_id)),
            filled_quantity=payload_decimal(payload.get("filled_quantity", current.filled_quantity)),
            average_price=(
                payload_decimal(payload["average_price"])
                if payload.get("average_price") not in (None, "")
                else current.average_price
            ),
            reduce_only=bool(payload.get("reduce_only", current.reduce_only)),
            raw_status=str(payload.get("status", current.raw_status or current.status.value)),
            client_order_id=str(payload["client_order_id"]) if payload.get("client_order_id") else current.client_order_id,
        )

    def _normalize_status(self, value: str) -> OrderStatus:
        normalized = value.strip().lower().replace(" ", "_")
        aliases = {
            "partiallyfilled": "partially_filled",
            "partially-filled": "partially_filled",
            "cancelled": "canceled",
        }
        normalized = aliases.get(normalized, normalized)
        return OrderStatus(normalized)

    def _merge_order(self, previous: Order, latest: Order) -> Order:
        return Order(
            exchange=latest.exchange or previous.exchange,
            symbol=latest.symbol or previous.symbol,
            market_type=latest.market_type,
            side=latest.side,
            quantity=latest.quantity or previous.quantity,
            price=latest.price if latest.price is not None else previous.price,
            status=latest.status,
            order_id=latest.order_id or previous.order_id,
            client_order_id=latest.client_order_id or previous.client_order_id,
            filled_quantity=max(previous.filled_quantity, latest.filled_quantity),
            average_price=latest.average_price if latest.average_price is not None else previous.average_price,
            reduce_only=latest.reduce_only or previous.reduce_only,
            raw_status=latest.raw_status or previous.raw_status,
            ts=latest.ts,
        )

    def _merge_cancel(self, previous: Order, canceled: Order) -> Order:
        merged = self._merge_order(previous, canceled)
        return Order(
            exchange=merged.exchange,
            symbol=merged.symbol,
            market_type=merged.market_type,
            side=merged.side,
            quantity=previous.quantity,
            price=merged.price,
            status=OrderStatus.CANCELED,
            order_id=merged.order_id,
            client_order_id=merged.client_order_id,
            filled_quantity=previous.filled_quantity,
            average_price=previous.average_price or merged.average_price,
            reduce_only=merged.reduce_only,
            raw_status=merged.raw_status or "CANCELED",
            ts=merged.ts,
        )


def payload_decimal(value: Any) -> Any:
    from decimal import Decimal

    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))
