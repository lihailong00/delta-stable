from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.models import MarketType, Order, OrderStatus, Position, PositionDirection, Side
from arb.runtime.recovery import WorkflowRecovery
from arb.storage.db import Database
from arb.storage.repository import Repository


@dataclass
class _RecoveryClient:
    positions: tuple[Position, ...]
    orders: tuple[Order, ...]

    async def fetch_positions(self, market_type: MarketType, *, symbol: str | None = None) -> tuple[Position, ...]:
        return self.positions

    async def fetch_open_orders(
        self,
        symbol: str | None = None,
        market_type: MarketType = MarketType.PERPETUAL,
    ) -> tuple[Order, ...]:
        return self.orders


@pytest.mark.asyncio
class TestWorkflowRecovery:
    async def test_recovery_loads_running_workflows_and_reconciles_state(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        try:
            db_path = Path(temp_dir.name) / "arb.sqlite3"
            database = Database(db_path)
            database.initialize()
            repository = Repository(database)
            repository.save_workflow_state(
                workflow_id="wf-1",
                workflow_type="open_position",
                exchange="binance",
                symbol="BTC/USDT",
                status="running",
                payload={"step": "waiting_fill"},
            )
            repository.save_position(
                Position(
                    exchange="binance",
                    symbol="BTC/USDT",
                    market_type=MarketType.PERPETUAL,
                    direction=PositionDirection.SHORT,
                    quantity=Decimal("1"),
                    entry_price=Decimal("100"),
                    mark_price=Decimal("99"),
                )
            )
            repository.save_order(
                Order(
                    exchange="binance",
                    symbol="BTC/USDT",
                    market_type=MarketType.PERPETUAL,
                    side=Side.SELL,
                    quantity=Decimal("1"),
                    price=Decimal("100"),
                    status=OrderStatus.NEW,
                    order_id="ord-1",
                )
            )
            client = _RecoveryClient(
                positions=(
                    Position(
                        exchange="binance",
                        symbol="BTC/USDT",
                        market_type=MarketType.PERPETUAL,
                        direction=PositionDirection.SHORT,
                        quantity=Decimal("0.8"),
                        entry_price=Decimal("100"),
                        mark_price=Decimal("99"),
                    ),
                ),
                orders=(),
            )

            plan = await WorkflowRecovery(repository).recover(client, exchange="binance")

            assert len(plan.workflows) == 1
            assert plan.workflows[0]["payload"]["step"] == "waiting_fill"
            assert not plan.reconciliation.ok
            assert plan.reconciliation.position_issues[0].issue == "position_quantity_mismatch"
            assert plan.reconciliation.order_issues[0].issue == "stale_local_open_order"
        finally:
            temp_dir.cleanup()
