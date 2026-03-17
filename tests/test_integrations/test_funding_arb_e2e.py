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
from arb.runtime.exchange_manager import LiveExchangeManager, ScanTarget
from arb.runtime.funding_arb_service import FundingArbService
from arb.runtime.pipeline import OpportunityPipeline
from arb.runtime.realtime_scanner import RealtimeScanner
from arb.runtime.supervisor import RuntimeSupervisor
from arb.scanner.funding_scanner import FundingScanner
from arb.workflows.close_position import ClosePositionWorkflow
from arb.workflows.open_position import OpenPositionWorkflow, VenueClients


async def _sleep(_: float) -> None:
    return None


def _snapshot(rate: str) -> dict[str, object]:
    ts = datetime(2026, 3, 17, tzinfo=timezone.utc).isoformat()
    return {
        "ticker": {
            "exchange": "binance",
            "symbol": "BTC/USDT",
            "market_type": "perpetual",
            "bid": "100.0",
            "ask": "100.2",
            "last": "100.1",
            "ts": ts,
        },
        "funding": {
            "exchange": "binance",
            "symbol": "BTC/USDT",
            "rate": rate,
            "predicted_rate": rate,
            "next_funding_time": datetime(2026, 3, 17, 8, tzinfo=timezone.utc).isoformat(),
            "ts": ts,
        },
        "top_ask_size": "10",
    }


def _order(
    *,
    market_type: MarketType,
    side: Side,
    order_id: str,
    reduce_only: bool = False,
) -> Order:
    return Order(
        exchange="binance",
        symbol="BTC/USDT",
        market_type=market_type,
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

    async def public_ping(self) -> bool:
        return True

    async def fetch_public_snapshot(self, symbol: str, market_type: MarketType) -> dict[str, object]:
        return self.snapshots.pop(0)


class _Repository:
    def __init__(self) -> None:
        self.workflows: list[dict[str, object]] = []
        self.tickers: list[object] = []
        self.funding: list[object] = []
        self.orders: list[object] = []
        self.positions: list[object] = []

    def save_workflow_state(self, **payload) -> None:
        self.workflows.append(payload)

    def save_ticker(self, ticker) -> None:
        self.tickers.append(ticker)

    def save_funding(self, funding) -> None:
        self.funding.append(funding)

    def save_order(self, order) -> None:
        self.orders.append(order)

    def save_fill(self, fill) -> None:
        return None

    def save_position(self, position) -> None:
        self.positions.append(position)


@pytest.mark.asyncio
async def test_funding_arb_e2e_signal_to_open_and_close() -> None:
    runtime = _SequenceRuntime([_snapshot("0.001"), _snapshot("-0.0002")])
    manager = LiveExchangeManager({"binance": runtime})
    repository = _Repository()
    scanner = RealtimeScanner(
        manager,
        FundingScanner(min_net_rate=Decimal("0.0001")),
        OpportunityPipeline(repository=repository),
        interval=0,
    )
    spot_client = _Client(
        orders=[_order(market_type=MarketType.SPOT, side=Side.BUY, order_id="spot-open"), _order(market_type=MarketType.SPOT, side=Side.SELL, order_id="spot-close")],
        fetched_orders=[_order(market_type=MarketType.SPOT, side=Side.BUY, order_id="spot-open"), _order(market_type=MarketType.SPOT, side=Side.SELL, order_id="spot-close")],
    )
    perp_client = _Client(
        orders=[_order(market_type=MarketType.PERPETUAL, side=Side.SELL, order_id="perp-open"), _order(market_type=MarketType.PERPETUAL, side=Side.BUY, order_id="perp-close", reduce_only=True)],
        fetched_orders=[_order(market_type=MarketType.PERPETUAL, side=Side.SELL, order_id="perp-open"), _order(market_type=MarketType.PERPETUAL, side=Side.BUY, order_id="perp-close", reduce_only=True)],
    )
    service = FundingArbService(
        scanner=scanner,
        open_workflow=OpenPositionWorkflow(executor=PairExecutor(tracker=OrderTracker(max_polls=1, poll_interval=0, sleep=_sleep))),
        close_workflow=ClosePositionWorkflow(executor=PairExecutor(tracker=OrderTracker(max_polls=1, poll_interval=0, sleep=_sleep))),
        venues={"binance": VenueClients(exchange="binance", spot_client=spot_client, perp_client=perp_client)},
        manager=manager,
        pipeline=OpportunityPipeline(repository=repository),
    )
    targets = [ScanTarget("binance", "BTC/USDT", MarketType.PERPETUAL)]

    first = await service.run_once(targets, dry_run=True)
    second = await service.run_once(targets, dry_run=True)

    assert len(first["scan"]["opportunities"]) == 1
    assert len(first["opened"]) == 1
    assert len(second["closed"]) == 1
    assert repository.workflows[-1]["status"] == "closed"
    assert len(repository.orders) == 4
    assert len(repository.positions) == 4


@pytest.mark.asyncio
async def test_supervisor_recovers_iteration_failure_and_runs_service() -> None:
    runtime = _SequenceRuntime([_snapshot("0.001")])
    manager = LiveExchangeManager({"binance": runtime})
    repository = _Repository()
    scanner = RealtimeScanner(
        manager,
        FundingScanner(min_net_rate=Decimal("0.0001")),
        OpportunityPipeline(repository=repository),
        interval=0,
    )
    spot_client = _Client(
        orders=[_order(market_type=MarketType.SPOT, side=Side.BUY, order_id="spot-open")],
        fetched_orders=[_order(market_type=MarketType.SPOT, side=Side.BUY, order_id="spot-open")],
    )
    perp_client = _Client(
        orders=[_order(market_type=MarketType.PERPETUAL, side=Side.SELL, order_id="perp-open")],
        fetched_orders=[_order(market_type=MarketType.PERPETUAL, side=Side.SELL, order_id="perp-open")],
    )
    service = FundingArbService(
        scanner=scanner,
        open_workflow=OpenPositionWorkflow(executor=PairExecutor(tracker=OrderTracker(max_polls=1, poll_interval=0, sleep=_sleep))),
        close_workflow=ClosePositionWorkflow(executor=PairExecutor(tracker=OrderTracker(max_polls=1, poll_interval=0, sleep=_sleep))),
        venues={"binance": VenueClients(exchange="binance", spot_client=spot_client, perp_client=perp_client)},
        manager=manager,
        pipeline=OpportunityPipeline(repository=repository),
    )
    targets = [ScanTarget("binance", "BTC/USDT", MarketType.PERPETUAL)]
    state = {"fail_once": True}

    async def runner():
        if state["fail_once"]:
            state["fail_once"] = False
            raise RuntimeError("temporary_loop_failure")
        return await service.run_once(targets, dry_run=True)

    supervisor = RuntimeSupervisor(runner, max_restarts=1, sleep=_sleep)

    results = await supervisor.run_forever(iterations=1)

    assert len(results) == 1
    assert len(results[0]["opened"]) == 1
    assert supervisor.snapshot()["restart_count"] == 1
