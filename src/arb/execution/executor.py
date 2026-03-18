"""Pair execution orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from arb.execution.guards import GuardContext, PreTradeGuards
from arb.execution.order_tracker import OrderTrackResult, OrderTracker
from arb.execution.protocols import CreateOrderClient, supports_cancel_order
from arb.models import Fill, MarketType, Order, OrderStatus


@dataclass(slots=True, frozen=True)
class ExecutionLeg:
    client: CreateOrderClient
    symbol: str
    market_type: MarketType
    side: str
    quantity: Decimal
    price: Decimal
    reduce_only: bool = False
    context: GuardContext | None = None


@dataclass(slots=True)
class ExecutionResult:
    status: str
    orders: list[Order] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)
    adjustments: list[Order] = field(default_factory=list)
    rollback_performed: bool = False
    reason: str = ""


class PairExecutor:
    """Execute paired arbitrage legs with rollback and hedge adjustment."""

    def __init__(
        self,
        guards: PreTradeGuards | None = None,
        *,
        tracker: OrderTracker | None = None,
    ) -> None:
        self.guards = guards or PreTradeGuards()
        self.tracker = tracker or OrderTracker()

    async def execute_pair(self, first_leg: ExecutionLeg, second_leg: ExecutionLeg) -> ExecutionResult:
        self._validate_leg(first_leg)
        self._validate_leg(second_leg)

        result = ExecutionResult(status="pending")
        try:
            first_order = await self._submit(first_leg)
            second_order = await self._submit(second_leg)
        except Exception as exc:
            if "first_order" in locals():
                await self._rollback(first_leg, first_order)
                result.rollback_performed = True
            result.status = "failed"
            result.reason = str(exc)
            return result

        first_tracked = await self.tracker.track_order(
            first_leg.client,
            first_order,
            symbol=first_leg.symbol,
            market_type=first_leg.market_type,
        )
        second_tracked = await self.tracker.track_order(
            second_leg.client,
            second_order,
            symbol=second_leg.symbol,
            market_type=second_leg.market_type,
        )
        result.orders = [first_tracked.final_order, second_tracked.final_order]
        result.fills = [*first_tracked.fills, *second_tracked.fills]

        if self._tracking_failed(first_tracked, second_tracked):
            result.status = "failed"
            result.reason = "order tracking timeout"
            return result

        result.adjustments = await self.reconcile_partial_fill(first_leg, second_leg, result.orders)
        if result.adjustments:
            result.status = "adjusted"
        elif all(order.status is OrderStatus.FILLED or order.filled_quantity >= order.quantity for order in result.orders):
            result.status = "filled"
        else:
            result.status = "filled"
        return result

    async def reconcile_partial_fill(
        self,
        first_leg: ExecutionLeg,
        second_leg: ExecutionLeg,
        orders: list[Order],
    ) -> list[Order]:
        if len(orders) != 2:
            return []
        first_filled = Decimal(str(getattr(orders[0], "filled_quantity", first_leg.quantity)))
        second_filled = Decimal(str(getattr(orders[1], "filled_quantity", second_leg.quantity)))
        if first_filled == second_filled:
            return []
        delta = abs(first_filled - second_filled)
        target_leg = second_leg if first_filled > second_filled else first_leg
        adjustment = await target_leg.client.create_order(
            target_leg.symbol,
            target_leg.market_type,
            target_leg.side,
            delta,
            price=target_leg.price,
            reduce_only=target_leg.reduce_only,
        )
        return [adjustment]

    async def _submit(self, leg: ExecutionLeg) -> Order:
        return await leg.client.create_order(
            leg.symbol,
            leg.market_type,
            leg.side,
            leg.quantity,
            price=leg.price,
            reduce_only=leg.reduce_only,
        )

    async def _rollback(self, leg: ExecutionLeg, order: Order) -> None:
        order_id = getattr(order, "order_id", None)
        if order_id and supports_cancel_order(leg.client):
            await leg.client.cancel_order(order_id, leg.symbol, leg.market_type)

    def _validate_leg(self, leg: ExecutionLeg) -> None:
        if leg.context is None:
            return
        self.guards.validate(
            symbol=leg.symbol,
            quantity=leg.quantity,
            price=leg.price,
            context=leg.context,
        )

    def _tracking_failed(self, first: OrderTrackResult, second: OrderTrackResult) -> bool:
        tracks = (first, second)
        return any(track.timed_out and track.final_order.filled_quantity == 0 for track in tracks)
