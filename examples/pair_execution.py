"""离线示例：双腿执行、部分成交补单、失败回滚。

运行：
PYTHONPATH=src uv run python examples/pair_execution.py
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal

from arb.execution.executor import ExecutionLeg, PairExecutor
from arb.execution.guards import GuardContext
from arb.models import MarketType, Order, OrderStatus, Side


@dataclass
class _FakeClient:
    orders: list[Order]
    fail_after: int | None = None

    def __post_init__(self) -> None:
        self._index = 0
        self.canceled: list[str] = []

    async def create_order(self, symbol, market_type, side, quantity, *, price=None, reduce_only=False):
        if self.fail_after is not None and self._index >= self.fail_after:
            raise RuntimeError("submit failed")
        order = self.orders[min(self._index, len(self.orders) - 1)]
        self._index += 1
        return order

    async def cancel_order(self, order_id, symbol, market_type):
        self.canceled.append(order_id)
        return None


async def run_partial_fill_demo() -> None:
    buy_client = _FakeClient(
        orders=[
            Order(
                exchange="okx",
                symbol="ETH/USDT",
                market_type=MarketType.SPOT,
                side=Side.BUY,
                quantity=Decimal("1"),
                price=Decimal("10"),
                status=OrderStatus.FILLED,
                order_id="spot-1",
                filled_quantity=Decimal("1"),
            )
        ]
    )
    sell_client = _FakeClient(
        orders=[
            Order(
                exchange="okx",
                symbol="ETH/USDT",
                market_type=MarketType.PERPETUAL,
                side=Side.SELL,
                quantity=Decimal("1"),
                price=Decimal("10"),
                status=OrderStatus.PARTIALLY_FILLED,
                order_id="perp-1",
                filled_quantity=Decimal("0.6"),
            ),
            Order(
                exchange="okx",
                symbol="ETH/USDT",
                market_type=MarketType.PERPETUAL,
                side=Side.SELL,
                quantity=Decimal("0.4"),
                price=Decimal("10"),
                status=OrderStatus.NEW,
                order_id="perp-adjust-1",
                filled_quantity=Decimal("0"),
            ),
        ]
    )
    context = GuardContext(
        available_balance=Decimal("1000"),
        max_notional=Decimal("1000"),
        supported_symbols={"ETH/USDT"},
    )
    executor = PairExecutor()
    result = await executor.execute_pair(
        ExecutionLeg(buy_client, "ETH/USDT", MarketType.SPOT, "buy", Decimal("1"), Decimal("10"), context=context),
        ExecutionLeg(sell_client, "ETH/USDT", MarketType.PERPETUAL, "sell", Decimal("1"), Decimal("10"), context=context),
    )
    print("partial fill result", result)


async def run_rollback_demo() -> None:
    first_leg_client = _FakeClient(
        orders=[
            Order(
                exchange="gate",
                symbol="BTC/USDT",
                market_type=MarketType.SPOT,
                side=Side.BUY,
                quantity=Decimal("1"),
                price=Decimal("100"),
                status=OrderStatus.NEW,
                order_id="spot-open-1",
                filled_quantity=Decimal("0"),
            )
        ]
    )
    second_leg_client = _FakeClient(orders=[], fail_after=0)
    context = GuardContext(
        available_balance=Decimal("1000"),
        max_notional=Decimal("1000"),
        supported_symbols={"BTC/USDT"},
    )
    executor = PairExecutor()
    result = await executor.execute_pair(
        ExecutionLeg(first_leg_client, "BTC/USDT", MarketType.SPOT, "buy", Decimal("1"), Decimal("100"), context=context),
        ExecutionLeg(second_leg_client, "BTC/USDT", MarketType.PERPETUAL, "sell", Decimal("1"), Decimal("100"), context=context),
    )
    print("rollback result", result)
    print("canceled orders", first_leg_client.canceled)


async def main() -> None:
    await run_partial_fill_demo()
    await run_rollback_demo()


if __name__ == "__main__":
    asyncio.run(main())
