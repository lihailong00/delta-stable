from __future__ import annotations

import sys
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from arb.execution.order_tracker import OrderTracker
from arb.models import Fill, MarketType, Order, OrderStatus, Side


@dataclass
class _TrackingClient:
    states: list[Order]
    fills: list[Fill] = field(default_factory=list)
    canceled: list[str] = field(default_factory=list)

    async def fetch_order(self, order_id: str, symbol: str, market_type: MarketType) -> Order:
        index = 0 if len(self.states) == 1 else 0
        order = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        return order

    async def cancel_order(self, order_id: str, symbol: str, market_type: MarketType):
        self.canceled.append(order_id)
        return Order(
            exchange='binance',
            symbol=symbol,
            market_type=market_type,
            side=Side.BUY,
            quantity=Decimal('1'),
            price=Decimal('100'),
            status=OrderStatus.CANCELED,
            order_id=order_id,
        )

    async def fetch_fills(self, order_id: str, symbol: str, market_type: MarketType):
        return self.fills


@pytest.mark.asyncio
class TestOrderTracker:

    async def test_tracker_waits_until_terminal_fill(self) -> None:
        tracker = OrderTracker(max_polls=3, poll_interval=0, sleep=lambda _: None)
        initial = Order(
            exchange='binance',
            symbol='BTC/USDT',
            market_type=MarketType.SPOT,
            side=Side.BUY,
            quantity=Decimal('1'),
            price=Decimal('100'),
            status=OrderStatus.NEW,
            order_id='o1',
        )
        client = _TrackingClient(
            states=[
                Order(exchange='binance', symbol='BTC/USDT', market_type=MarketType.SPOT, side=Side.BUY, quantity=Decimal('1'), price=Decimal('100'), status=OrderStatus.NEW, order_id='o1'),
                Order(exchange='binance', symbol='BTC/USDT', market_type=MarketType.SPOT, side=Side.BUY, quantity=Decimal('1'), price=Decimal('100'), status=OrderStatus.FILLED, order_id='o1', filled_quantity=Decimal('1')),
            ],
            fills=[
                Fill(exchange='binance', symbol='BTC/USDT', market_type=MarketType.SPOT, side=Side.BUY, quantity=Decimal('1'), price=Decimal('100'), order_id='o1', fill_id='f1')
            ],
        )
        result = await tracker.track_order(client, initial, symbol='BTC/USDT', market_type=MarketType.SPOT)
        assert result.final_order.status is OrderStatus.FILLED
        assert result.polls == 2
        assert result.fills[0].fill_id == 'f1'

    async def test_tracker_cancels_order_on_timeout(self) -> None:
        tracker = OrderTracker(max_polls=2, poll_interval=0, sleep=lambda _: None)
        initial = Order(
            exchange='binance',
            symbol='BTC/USDT',
            market_type=MarketType.SPOT,
            side=Side.BUY,
            quantity=Decimal('1'),
            price=Decimal('100'),
            status=OrderStatus.NEW,
            order_id='o2',
        )
        client = _TrackingClient(
            states=[
                Order(exchange='binance', symbol='BTC/USDT', market_type=MarketType.SPOT, side=Side.BUY, quantity=Decimal('1'), price=Decimal('100'), status=OrderStatus.NEW, order_id='o2'),
                Order(exchange='binance', symbol='BTC/USDT', market_type=MarketType.SPOT, side=Side.BUY, quantity=Decimal('1'), price=Decimal('100'), status=OrderStatus.NEW, order_id='o2'),
            ]
        )
        result = await tracker.track_order(client, initial, symbol='BTC/USDT', market_type=MarketType.SPOT)
        assert result.timed_out
        assert result.canceled
        assert result.final_order.status is OrderStatus.CANCELED
        assert client.canceled == ['o2']
