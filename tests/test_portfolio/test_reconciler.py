from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.models import MarketType, Order, OrderStatus, Position, PositionDirection, Side
from arb.portfolio.reconciler import PortfolioReconciler


class TestPortfolioReconciler:
    def test_reconcile_reports_position_and_order_mismatches(self) -> None:
        reconciler = PortfolioReconciler()
        local_positions = [
            {
                "exchange": "binance",
                "symbol": "BTC/USDT",
                "market_type": "perpetual",
                "direction": "short",
                "quantity": "1",
            }
        ]
        exchange_positions = [
            Position(
                exchange="binance",
                symbol="BTC/USDT",
                market_type=MarketType.PERPETUAL,
                direction=PositionDirection.SHORT,
                quantity=Decimal("0.8"),
                entry_price=Decimal("100"),
                mark_price=Decimal("99"),
            )
        ]
        local_orders = [
            {
                "order_id": "ord-1",
                "status": "new",
            }
        ]
        exchange_orders = [
            Order(
                exchange="binance",
                symbol="BTC/USDT",
                market_type=MarketType.PERPETUAL,
                side=Side.SELL,
                quantity=Decimal("1"),
                price=Decimal("100"),
                status=OrderStatus.FILLED,
                order_id="ord-1",
                filled_quantity=Decimal("1"),
            )
        ]

        report = reconciler.reconcile(
            local_positions=local_positions,
            exchange_positions=exchange_positions,
            local_orders=local_orders,
            exchange_orders=exchange_orders,
        )

        assert not report.ok
        assert report.position_issues[0].issue == "position_quantity_mismatch"
        assert report.order_issues[0].issue == "order_status_mismatch"
