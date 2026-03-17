"""离线示例：初始化 sqlite 并保存订单、仓位、ticker、funding。

运行：
PYTHONPATH=src uv run python examples/storage_repository.py
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from tempfile import TemporaryDirectory
from pathlib import Path

from arb.models import FundingRate, MarketType, Order, OrderStatus, Position, PositionDirection, Side, Ticker
from arb.storage.db import Database
from arb.storage.repository import Repository


def main() -> None:
    with TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "arb.sqlite3"
        database = Database(db_path)
        database.initialize()
        repository = Repository(database)
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)

        repository.save_ticker(
            Ticker(
                exchange="binance",
                symbol="BTC/USDT",
                market_type=MarketType.SPOT,
                bid=Decimal("100"),
                ask=Decimal("100.2"),
                last=Decimal("100.1"),
                ts=now,
            )
        )
        repository.save_funding(
            FundingRate(
                exchange="binance",
                symbol="BTC/USDT",
                rate=Decimal("0.0007"),
                predicted_rate=Decimal("0.0008"),
                next_funding_time=now,
                ts=now,
            )
        )
        repository.save_position(
            Position(
                exchange="binance",
                symbol="BTC/USDT",
                market_type=MarketType.SPOT,
                direction=PositionDirection.LONG,
                quantity=Decimal("1"),
                entry_price=Decimal("100"),
                mark_price=Decimal("101"),
                unrealized_pnl=Decimal("1"),
                ts=now,
            )
        )
        repository.save_order(
            Order(
                exchange="binance",
                symbol="BTC/USDT",
                market_type=MarketType.SPOT,
                side=Side.BUY,
                quantity=Decimal("1"),
                price=Decimal("100"),
                status=OrderStatus.FILLED,
                order_id="order-1",
                filled_quantity=Decimal("1"),
                average_price=Decimal("100"),
                ts=now,
            )
        )

        print("orders", repository.list_orders())
        print("positions", repository.list_positions())
        print("funding history", repository.list_funding_history(exchange="binance"))


if __name__ == "__main__":
    main()
