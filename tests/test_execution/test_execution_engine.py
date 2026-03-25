from __future__ import annotations

import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from arb.execution.executor import ExecutionLeg, PairExecutor
from arb.execution.guards import GuardContext, GuardViolation, PreTradeGuards
from arb.execution.order_tracker import OrderTracker
from arb.execution.router import ExecutionRouter
from arb.models import Fill, MarketType, Order, OrderStatus, Side

@dataclass
class _FakeClient:
    orders: list[Order]
    fail_after: int | None = None
    canceled: list[str] | None = None

    def __post_init__(self) -> None:
        if self.canceled is None:
            self.canceled = []
        self._index = 0

    async def create_order(self, symbol, market_type, side, quantity, *, price=None, reduce_only=False):
        if self.fail_after is not None and self._index >= self.fail_after:
            raise RuntimeError('submit failed')
        order = self.orders[min(self._index, len(self.orders) - 1)]
        self._index += 1
        return order

    async def cancel_order(self, order_id, symbol, market_type):
        self.canceled.append(order_id)
        return None


@dataclass
class _TrackingClient(_FakeClient):
    fetched_orders: list[Order] | None = None
    fills: list[Fill] | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.fetched_orders is None:
            self.fetched_orders = []
        if self.fills is None:
            self.fills = []

    async def fetch_order(self, order_id, symbol, market_type):
        if self.fetched_orders:
            return self.fetched_orders.pop(0)
        return self.orders[min(self._index - 1, len(self.orders) - 1)]

    async def fetch_fills(self, order_id, symbol, market_type):
        return self.fills

class TestPreTradeGuards:

    def test_guard_blocks_limit_and_balance_violations(self) -> None:
        guards = PreTradeGuards()
        context = GuardContext(available_balance=Decimal('100'), max_notional=Decimal('80'), supported_symbols={'BTC/USDT'})
        with pytest.raises(GuardViolation):
            guards.validate(symbol='BTC/USDT', quantity=Decimal('1'), price=Decimal('100'), context=context)

class TestExecutionRouter:

    def test_router_chooses_mode_and_fallback_exchange(self) -> None:
        router = ExecutionRouter()
        decision = router.route(preferred_exchange='binance', fallback_exchange='okx', exchange_available=False, urgent=False, maker_fee_rate=Decimal('0.0001'), taker_fee_rate=Decimal('0.0004'), spread_bps=Decimal('5'))
        assert decision.mode == 'maker'
        assert decision.exchange == 'okx'

@pytest.mark.asyncio
class TestPairExecutor:

    async def test_dual_leg_execution_succeeds(self) -> None:
        client_a = _FakeClient(orders=[Order(exchange='binance', symbol='BTC/USDT', market_type=MarketType.SPOT, side=Side.BUY, quantity=Decimal('1'), price=Decimal('100'), status=OrderStatus.FILLED, order_id='a1', filled_quantity=Decimal('1'))])
        client_b = _FakeClient(orders=[Order(exchange='binance', symbol='BTC/USDT', market_type=MarketType.PERPETUAL, side=Side.SELL, quantity=Decimal('1'), price=Decimal('100'), status=OrderStatus.FILLED, order_id='b1', filled_quantity=Decimal('1'))])
        context = GuardContext(available_balance=Decimal('1000'), max_notional=Decimal('1000'), supported_symbols={'BTC/USDT'})
        executor = PairExecutor()
        result = await executor.execute_pair(ExecutionLeg(client_a, 'BTC/USDT', MarketType.SPOT, 'buy', Decimal('1'), Decimal('100'), context=context), ExecutionLeg(client_b, 'BTC/USDT', MarketType.PERPETUAL, 'sell', Decimal('1'), Decimal('100'), context=context))
        assert result.status == 'filled'
        assert len(result.orders) == 2

    async def test_partial_fill_triggers_adjustment_order(self) -> None:
        client_a = _FakeClient(orders=[Order(exchange='okx', symbol='ETH/USDT', market_type=MarketType.SPOT, side=Side.BUY, quantity=Decimal('1'), price=Decimal('10'), status=OrderStatus.FILLED, order_id='a1', filled_quantity=Decimal('1'))])
        client_b = _FakeClient(orders=[Order(exchange='okx', symbol='ETH/USDT', market_type=MarketType.PERPETUAL, side=Side.SELL, quantity=Decimal('1'), price=Decimal('10'), status=OrderStatus.PARTIALLY_FILLED, order_id='b1', filled_quantity=Decimal('0.6')), Order(exchange='okx', symbol='ETH/USDT', market_type=MarketType.PERPETUAL, side=Side.SELL, quantity=Decimal('0.4'), price=Decimal('10'), status=OrderStatus.NEW, order_id='b2', filled_quantity=Decimal('0'))])
        context = GuardContext(available_balance=Decimal('1000'), max_notional=Decimal('1000'), supported_symbols={'ETH/USDT'})
        executor = PairExecutor()
        result = await executor.execute_pair(ExecutionLeg(client_a, 'ETH/USDT', MarketType.SPOT, 'buy', Decimal('1'), Decimal('10'), context=context), ExecutionLeg(client_b, 'ETH/USDT', MarketType.PERPETUAL, 'sell', Decimal('1'), Decimal('10'), context=context))
        assert result.status == 'adjusted'
        assert len(result.adjustments) == 1
        assert result.adjustments[0].order_id == 'b2'

    async def test_failed_second_leg_rolls_back_first_leg(self) -> None:
        client_a = _FakeClient(orders=[Order(exchange='gate', symbol='BTC/USDT', market_type=MarketType.SPOT, side=Side.BUY, quantity=Decimal('1'), price=Decimal('100'), status=OrderStatus.NEW, order_id='a1', filled_quantity=Decimal('0'))])
        client_b = _FakeClient(orders=[], fail_after=0)
        context = GuardContext(available_balance=Decimal('1000'), max_notional=Decimal('1000'), supported_symbols={'BTC/USDT'})
        executor = PairExecutor()
        result = await executor.execute_pair(ExecutionLeg(client_a, 'BTC/USDT', MarketType.SPOT, 'buy', Decimal('1'), Decimal('100'), context=context), ExecutionLeg(client_b, 'BTC/USDT', MarketType.PERPETUAL, 'sell', Decimal('1'), Decimal('100'), context=context))
        assert result.status == 'failed'
        assert result.rollback_performed
        assert client_a.canceled == ['a1']

    async def test_executor_uses_tracker_to_observe_partial_fill_before_adjustment(self) -> None:
        client_a = _TrackingClient(
            orders=[Order(exchange='okx', symbol='ETH/USDT', market_type=MarketType.SPOT, side=Side.BUY, quantity=Decimal('1'), price=Decimal('10'), status=OrderStatus.NEW, order_id='a1')],
            fetched_orders=[Order(exchange='okx', symbol='ETH/USDT', market_type=MarketType.SPOT, side=Side.BUY, quantity=Decimal('1'), price=Decimal('10'), status=OrderStatus.FILLED, order_id='a1', filled_quantity=Decimal('1'))],
        )
        client_b = _TrackingClient(
            orders=[
                Order(exchange='okx', symbol='ETH/USDT', market_type=MarketType.PERPETUAL, side=Side.SELL, quantity=Decimal('1'), price=Decimal('10'), status=OrderStatus.NEW, order_id='b1'),
                Order(exchange='okx', symbol='ETH/USDT', market_type=MarketType.PERPETUAL, side=Side.SELL, quantity=Decimal('0.4'), price=Decimal('10'), status=OrderStatus.NEW, order_id='b2'),
            ],
            fetched_orders=[Order(exchange='okx', symbol='ETH/USDT', market_type=MarketType.PERPETUAL, side=Side.SELL, quantity=Decimal('1'), price=Decimal('10'), status=OrderStatus.PARTIALLY_FILLED, order_id='b1', filled_quantity=Decimal('0.6'))],
        )
        context = GuardContext(available_balance=Decimal('1000'), max_notional=Decimal('1000'), supported_symbols={'ETH/USDT'})
        executor = PairExecutor(tracker=OrderTracker(max_polls=1, poll_interval=0, sleep=lambda _: None))
        result = await executor.execute_pair(
            ExecutionLeg(client_a, 'ETH/USDT', MarketType.SPOT, 'buy', Decimal('1'), Decimal('10'), context=context),
            ExecutionLeg(client_b, 'ETH/USDT', MarketType.PERPETUAL, 'sell', Decimal('1'), Decimal('10'), context=context),
        )
        assert result.status == 'adjusted'
        assert result.orders[1].filled_quantity == Decimal('0.6')
        assert result.adjustments[0].order_id == 'b2'

    async def test_equal_partial_fill_returns_partial_status(self) -> None:
        client_a = _TrackingClient(
            orders=[Order(exchange='binance', symbol='BTC/USDT', market_type=MarketType.SPOT, side=Side.BUY, quantity=Decimal('1'), price=Decimal('100'), status=OrderStatus.NEW, order_id='a1')],
            fetched_orders=[Order(exchange='binance', symbol='BTC/USDT', market_type=MarketType.SPOT, side=Side.BUY, quantity=Decimal('1'), price=Decimal('100'), status=OrderStatus.PARTIALLY_FILLED, order_id='a1', filled_quantity=Decimal('0.1'))],
        )
        client_b = _TrackingClient(
            orders=[Order(exchange='binance', symbol='BTC/USDT', market_type=MarketType.PERPETUAL, side=Side.SELL, quantity=Decimal('1'), price=Decimal('100'), status=OrderStatus.NEW, order_id='b1')],
            fetched_orders=[Order(exchange='binance', symbol='BTC/USDT', market_type=MarketType.PERPETUAL, side=Side.SELL, quantity=Decimal('1'), price=Decimal('100'), status=OrderStatus.PARTIALLY_FILLED, order_id='b1', filled_quantity=Decimal('0.1'))],
        )
        context = GuardContext(available_balance=Decimal('1000'), max_notional=Decimal('1000'), supported_symbols={'BTC/USDT'})
        executor = PairExecutor(tracker=OrderTracker(max_polls=1, poll_interval=0, sleep=lambda _: None))

        result = await executor.execute_pair(
            ExecutionLeg(client_a, 'BTC/USDT', MarketType.SPOT, 'buy', Decimal('1'), Decimal('100'), context=context),
            ExecutionLeg(client_b, 'BTC/USDT', MarketType.PERPETUAL, 'sell', Decimal('1'), Decimal('100'), context=context),
        )

        assert result.status == 'partial'
        assert result.adjustments == []
