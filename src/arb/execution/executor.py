"""Pair execution orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from arb.execution.guards import GuardContext, PreTradeGuards
from arb.models import MarketType


@dataclass(slots=True, frozen=True)
class ExecutionLeg:
    client: Any
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
    orders: list[Any] = field(default_factory=list)
    adjustments: list[Any] = field(default_factory=list)
    rollback_performed: bool = False
    reason: str = ""


class PairExecutor:
    """Execute paired arbitrage legs with rollback and hedge adjustment."""

    def __init__(self, guards: PreTradeGuards | None = None) -> None:
        self.guards = guards or PreTradeGuards()

    async def execute_pair(self, first_leg: ExecutionLeg, second_leg: ExecutionLeg) -> ExecutionResult:
        self._validate_leg(first_leg)
        self._validate_leg(second_leg)

        result = ExecutionResult(status="pending")
        try:
            first_order = await self._submit(first_leg)
            result.orders.append(first_order)
            second_order = await self._submit(second_leg)
            result.orders.append(second_order)
        except Exception as exc:
            if result.orders:
                await self._rollback(first_leg, result.orders[0])
                result.rollback_performed = True
            result.status = "failed"
            result.reason = str(exc)
            return result

        result.adjustments = await self.reconcile_partial_fill(first_leg, second_leg, result.orders)
        result.status = "adjusted" if result.adjustments else "filled"
        return result

    async def reconcile_partial_fill(
        self,
        first_leg: ExecutionLeg,
        second_leg: ExecutionLeg,
        orders: list[Any],
    ) -> list[Any]:
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

    async def _submit(self, leg: ExecutionLeg) -> Any:
        return await leg.client.create_order(
            leg.symbol,
            leg.market_type,
            leg.side,
            leg.quantity,
            price=leg.price,
            reduce_only=leg.reduce_only,
        )

    async def _rollback(self, leg: ExecutionLeg, order: Any) -> None:
        order_id = getattr(order, "order_id", None)
        if order_id:
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
