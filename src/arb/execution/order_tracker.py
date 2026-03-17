"""Order lifecycle tracking helpers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from arb.models import Fill, MarketType, Order, OrderStatus

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
    ) -> None:
        self.max_polls = max_polls
        self.poll_interval = poll_interval
        self.sleep = sleep or asyncio.sleep

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
            current = self._merge_order(current, await client.fetch_order(str(order.order_id), symbol, market_type))
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
            return []
        return list(await client.fetch_fills(str(order_id), symbol, market_type))

    async def _sleep(self, delay: float) -> None:
        result = self.sleep(delay)
        if asyncio.iscoroutine(result):
            await result

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
