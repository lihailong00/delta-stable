from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.execution.executor import PairExecutor
from arb.execution.order_tracker import OrderTracker
from arb.models import MarketType, Order, OrderStatus, Side
from arb.runtime import CrossExchangeFundingService, LiveExchangeManager, OpportunityPipeline, ScanTarget
from arb.workflows import ClosePositionWorkflow, OpenPositionWorkflow, VenueClients


async def _sleep(_: float) -> None:
    return None


def _snapshot(exchange: str, rate: str, ask: str, bid: str) -> dict[str, object]:
    ts = datetime(2026, 3, 17, tzinfo=timezone.utc).isoformat()
    return {
        "ticker": {
            "exchange": exchange,
            "symbol": "ETH/USDT",
            "market_type": "perpetual",
            "bid": bid,
            "ask": ask,
            "last": ask,
            "ts": ts,
        },
        "funding": {
            "exchange": exchange,
            "symbol": "ETH/USDT",
            "rate": rate,
            "predicted_rate": rate,
            "next_funding_time": datetime(2026, 3, 17, 8, tzinfo=timezone.utc).isoformat(),
            "ts": ts,
        },
    }


def _order(
    *,
    exchange: str,
    side: Side,
    order_id: str,
    reduce_only: bool = False,
) -> Order:
    return Order(
        exchange=exchange,
        symbol="ETH/USDT",
        market_type=MarketType.PERPETUAL,
        side=side,
        quantity=Decimal("1"),
        price=Decimal("100"),
        status=OrderStatus.FILLED,
        order_id=order_id,
        filled_quantity=Decimal("1"),
        reduce_only=reduce_only,
    )


@dataclass
class _Client:
    orders: list[Order]
    fetched_orders: list[Order] = field(default_factory=list)

    async def create_order(
        self,
        symbol: str,
        market_type: MarketType,
        side: str,
        quantity: Decimal,
        *,
        price: Decimal | None = None,
        reduce_only: bool = False,
    ) -> Order:
        return self.orders.pop(0)

    async def cancel_order(self, order_id: str, symbol: str, market_type: MarketType) -> Order:
        return Order(
            exchange="binance",
            symbol=symbol,
            market_type=market_type,
            side=Side.BUY,
            quantity=Decimal("0"),
            price=None,
            status=OrderStatus.CANCELED,
            order_id=order_id,
        )

    async def fetch_order(self, order_id: str, symbol: str, market_type: MarketType) -> Order:
        return self.fetched_orders.pop(0)

    async def fetch_fills(self, order_id: str, symbol: str, market_type: MarketType) -> tuple[()]:
        return ()


class _SequenceRuntime:
    def __init__(self, snapshots: list[dict[str, object]]) -> None:
        self.snapshots = list(snapshots)

    async def fetch_public_snapshot(self, symbol: str, market_type: MarketType) -> dict[str, object]:
        return self.snapshots.pop(0)

    async def public_ping(self) -> bool:
        return True


class _Repository:
    def __init__(self) -> None:
        self.workflows: list[dict[str, object]] = []

    def save_workflow_state(self, **payload) -> None:
        self.workflows.append(payload)

    def save_order(self, order) -> None:
        return None

    def save_fill(self, fill) -> None:
        return None

    def save_position(self, position) -> None:
        return None


@pytest.mark.asyncio
async def test_cross_exchange_service_opens_then_closes() -> None:
    manager = LiveExchangeManager(
        {
            "okx": _SequenceRuntime(
                [
                    _snapshot("okx", "0.0001", "100", "99.9"),
                    _snapshot("okx", "0.0004", "100", "99.9"),
                ]
            ),
            "binance": _SequenceRuntime(
                [
                    _snapshot("binance", "0.0008", "100.2", "100.1"),
                    _snapshot("binance", "0.00045", "100.2", "100.1"),
                ]
            ),
        }
    )
    okx_client = _Client(
        orders=[
            _order(exchange="okx", side=Side.BUY, order_id="okx-open"),
            _order(exchange="okx", side=Side.SELL, order_id="okx-close", reduce_only=True),
        ],
        fetched_orders=[
            _order(exchange="okx", side=Side.BUY, order_id="okx-open"),
            _order(exchange="okx", side=Side.SELL, order_id="okx-close", reduce_only=True),
        ],
    )
    binance_client = _Client(
        orders=[
            _order(exchange="binance", side=Side.SELL, order_id="binance-open"),
            _order(exchange="binance", side=Side.BUY, order_id="binance-close", reduce_only=True),
        ],
        fetched_orders=[
            _order(exchange="binance", side=Side.SELL, order_id="binance-open"),
            _order(exchange="binance", side=Side.BUY, order_id="binance-close", reduce_only=True),
        ],
    )
    venues = {
        "okx": VenueClients(exchange="okx", spot_client=okx_client, perp_client=okx_client),
        "binance": VenueClients(exchange="binance", spot_client=binance_client, perp_client=binance_client),
    }
    service = CrossExchangeFundingService(
        manager=manager,
        pipeline=OpportunityPipeline(repository=_Repository()),
        open_workflow=OpenPositionWorkflow(executor=PairExecutor(tracker=OrderTracker(max_polls=1, poll_interval=0, sleep=_sleep))),
        close_workflow=ClosePositionWorkflow(executor=PairExecutor(tracker=OrderTracker(max_polls=1, poll_interval=0, sleep=_sleep))),
        venues=venues,
    )
    targets = [
        ScanTarget("okx", "ETH/USDT", MarketType.PERPETUAL),
        ScanTarget("binance", "ETH/USDT", MarketType.PERPETUAL),
    ]

    first = await service.run_once(targets)
    second = await service.run_once(targets)

    assert len(first["opened"]) == 1
    assert first["opened"][0].status == "opened"
    assert len(second["closed"]) == 1
    assert second["closed"][0].status == "closed"
