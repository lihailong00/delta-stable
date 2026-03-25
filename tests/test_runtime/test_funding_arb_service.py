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
from arb.market.schemas import MarketSnapshot
from arb.models import MarketType, Order, OrderStatus, Side
from arb.runtime.funding_arb_service import ActiveFundingArb
from arb.runtime.exchange_manager import LiveExchangeManager, ScanTarget
from arb.runtime.funding_arb_service import FundingArbService
from arb.runtime.pipeline import OpportunityPipeline
from arb.scanner.funding_scanner import FundingOpportunity
from arb.strategy.spot_perp import SpotPerpStrategy
from arb.workflows.close_position import ClosePositionWorkflow
from arb.workflows.open_position import OpenPositionWorkflow, VenueClients
from tests.factories import build_market_snapshot


async def _sleep(_: float) -> None:
    return None


def _opportunity(exchange: str, symbol: str, rate: str, *, interval_hours: int = 8) -> FundingOpportunity:
    decimal_rate = Decimal(rate)
    return FundingOpportunity(
        exchange=exchange,
        symbol=symbol,
        gross_rate=decimal_rate,
        net_rate=decimal_rate,
        funding_interval_hours=interval_hours,
        hourly_net_rate=decimal_rate / Decimal(interval_hours),
        daily_net_rate=decimal_rate * (Decimal("24") / Decimal(interval_hours)),
        annualized_net_rate=decimal_rate * (Decimal("24") / Decimal(interval_hours)) * Decimal("365"),
        spread_bps=Decimal("2"),
        liquidity_usd=Decimal("1000"),
    )


def _order(
    *,
    exchange: str,
    symbol: str,
    market_type: MarketType,
    side: Side,
    order_id: str,
    status: OrderStatus,
    filled_quantity: str = "1",
    price: str = "100",
    reduce_only: bool = False,
) -> Order:
    return Order(
        exchange=exchange,
        symbol=symbol,
        market_type=market_type,
        side=side,
        quantity=Decimal("1"),
        price=Decimal(price),
        status=status,
        order_id=order_id,
        filled_quantity=Decimal(filled_quantity),
        reduce_only=reduce_only,
    )


@dataclass
class _Client:
    orders: list[Order]
    fetched_orders: list[Order] = field(default_factory=list)
    submitted: list[dict[str, object]] = field(default_factory=list)

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
        self.submitted.append(
            {
                "symbol": symbol,
                "market_type": market_type,
                "side": side,
                "quantity": quantity,
                "price": price,
                "reduce_only": reduce_only,
            }
        )
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


class _SequenceScanner:
    def __init__(self, scans: list[dict[str, object]]) -> None:
        self.scans = list(scans)

    async def scan_once(self, targets, *, dry_run: bool = False):  # noqa: ANN001
        return self.scans.pop(0)

    def select_opportunities(self, opportunities, *, limit: int = 1, active_keys: set[str] | None = None):  # noqa: ANN001
        active = active_keys or set()
        selected = []
        for item in opportunities:
            key = f"{item.exchange}:{item.symbol}"
            if key in active:
                continue
            selected.append(item)
            if len(selected) >= limit:
                break
        return selected


class _MemoryRepository:
    def __init__(self) -> None:
        self.workflow_states: list[dict[str, object]] = []
        self.orders: list[Order] = []
        self.fills: list[object] = []
        self.positions: list[object] = []

    def save_workflow_state(self, **payload) -> None:
        self.workflow_states.append(payload)

    def save_order(self, order) -> None:
        self.orders.append(order)

    def save_fill(self, fill) -> None:
        self.fills.append(fill)

    def save_position(self, position) -> None:
        self.positions.append(position)


@pytest.mark.asyncio
class TestFundingArbService:
    async def test_service_opens_then_closes_position(self) -> None:
        spot_client = _Client(
            orders=[
                _order(exchange="binance", symbol="BTC/USDT", market_type=MarketType.SPOT, side=Side.BUY, order_id="spot-open", status=OrderStatus.FILLED),
                _order(exchange="binance", symbol="BTC/USDT", market_type=MarketType.SPOT, side=Side.SELL, order_id="spot-close", status=OrderStatus.FILLED),
            ],
            fetched_orders=[
                _order(exchange="binance", symbol="BTC/USDT", market_type=MarketType.SPOT, side=Side.BUY, order_id="spot-open", status=OrderStatus.FILLED),
                _order(exchange="binance", symbol="BTC/USDT", market_type=MarketType.SPOT, side=Side.SELL, order_id="spot-close", status=OrderStatus.FILLED),
            ],
        )
        perp_client = _Client(
            orders=[
                _order(exchange="binance", symbol="BTC/USDT", market_type=MarketType.PERPETUAL, side=Side.SELL, order_id="perp-open", status=OrderStatus.FILLED),
                _order(exchange="binance", symbol="BTC/USDT", market_type=MarketType.PERPETUAL, side=Side.BUY, order_id="perp-close", status=OrderStatus.FILLED, reduce_only=True),
            ],
            fetched_orders=[
                _order(exchange="binance", symbol="BTC/USDT", market_type=MarketType.PERPETUAL, side=Side.SELL, order_id="perp-open", status=OrderStatus.FILLED),
                _order(exchange="binance", symbol="BTC/USDT", market_type=MarketType.PERPETUAL, side=Side.BUY, order_id="perp-close", status=OrderStatus.FILLED, reduce_only=True),
            ],
        )
        venue = VenueClients(exchange="binance", spot_client=spot_client, perp_client=perp_client)
        scanner = _SequenceScanner(
            [
                {
                    "snapshots": [build_market_snapshot("binance", "BTC/USDT", rate="0.001")],
                    "opportunities": [_opportunity("binance", "BTC/USDT", "0.001")],
                    "output": [],
                },
                {
                    "snapshots": [build_market_snapshot("binance", "BTC/USDT", rate="-0.0001")],
                    "opportunities": [],
                    "output": [],
                },
            ]
        )
        repository = _MemoryRepository()
        service = FundingArbService(
            scanner=scanner,
            open_workflow=OpenPositionWorkflow(executor=PairExecutor(tracker=OrderTracker(max_polls=1, poll_interval=0, sleep=_sleep))),
            close_workflow=ClosePositionWorkflow(executor=PairExecutor(tracker=OrderTracker(max_polls=1, poll_interval=0, sleep=_sleep))),
            venues={"binance": venue},
            manager=LiveExchangeManager({}),
            pipeline=OpportunityPipeline(repository=repository),
        )
        targets = [ScanTarget("binance", "BTC/USDT", MarketType.PERPETUAL)]

        first = await service.run_once(targets)
        second = await service.run_once(targets)

        assert len(first["opened"]) == 1
        assert len(first["active"]) == 1
        assert len(second["closed"]) == 1
        assert len(second["active"]) == 0
        assert [item["status"] for item in repository.workflow_states] == ["opening", "open", "closing", "closed"]
        assert repository.workflow_states[-1]["payload"]["alert_count"] == 1
        assert repository.workflow_states[-1]["payload"]["alerts"] == [
            {"reason": "funding_reversal", "severity": "medium"}
        ]
        assert len(repository.orders) == 4
        assert len(repository.positions) == 4

    async def test_service_skips_duplicate_symbol_and_opens_next_opportunity(self) -> None:
        spot_client = _Client(
            orders=[
                _order(exchange="binance", symbol="BTC/USDT", market_type=MarketType.SPOT, side=Side.BUY, order_id="btc-spot-open", status=OrderStatus.FILLED),
                _order(exchange="binance", symbol="ETH/USDT", market_type=MarketType.SPOT, side=Side.BUY, order_id="eth-spot-open", status=OrderStatus.FILLED),
            ],
            fetched_orders=[
                _order(exchange="binance", symbol="BTC/USDT", market_type=MarketType.SPOT, side=Side.BUY, order_id="btc-spot-open", status=OrderStatus.FILLED),
                _order(exchange="binance", symbol="ETH/USDT", market_type=MarketType.SPOT, side=Side.BUY, order_id="eth-spot-open", status=OrderStatus.FILLED),
            ],
        )
        perp_client = _Client(
            orders=[
                _order(exchange="binance", symbol="BTC/USDT", market_type=MarketType.PERPETUAL, side=Side.SELL, order_id="btc-perp-open", status=OrderStatus.FILLED),
                _order(exchange="binance", symbol="ETH/USDT", market_type=MarketType.PERPETUAL, side=Side.SELL, order_id="eth-perp-open", status=OrderStatus.FILLED),
            ],
            fetched_orders=[
                _order(exchange="binance", symbol="BTC/USDT", market_type=MarketType.PERPETUAL, side=Side.SELL, order_id="btc-perp-open", status=OrderStatus.FILLED),
                _order(exchange="binance", symbol="ETH/USDT", market_type=MarketType.PERPETUAL, side=Side.SELL, order_id="eth-perp-open", status=OrderStatus.FILLED),
            ],
        )
        scanner = _SequenceScanner(
            [
                {
                    "snapshots": [
                        build_market_snapshot("binance", "BTC/USDT", rate="0.001"),
                        build_market_snapshot("binance", "ETH/USDT", rate="0.0008"),
                    ],
                    "opportunities": [
                        _opportunity("binance", "BTC/USDT", "0.001"),
                        _opportunity("binance", "ETH/USDT", "0.0008"),
                    ],
                    "output": [],
                },
                {
                    "snapshots": [
                        build_market_snapshot("binance", "BTC/USDT", rate="0.001"),
                        build_market_snapshot("binance", "ETH/USDT", rate="0.0008"),
                    ],
                    "opportunities": [
                        _opportunity("binance", "BTC/USDT", "0.001"),
                        _opportunity("binance", "ETH/USDT", "0.0008"),
                    ],
                    "output": [],
                },
            ]
        )
        service = FundingArbService(
            scanner=scanner,
            open_workflow=OpenPositionWorkflow(executor=PairExecutor(tracker=OrderTracker(max_polls=1, poll_interval=0, sleep=_sleep))),
            close_workflow=ClosePositionWorkflow(executor=PairExecutor(tracker=OrderTracker(max_polls=1, poll_interval=0, sleep=_sleep))),
            venues={"binance": VenueClients(exchange="binance", spot_client=spot_client, perp_client=perp_client)},
            manager=LiveExchangeManager({}),
            pipeline=OpportunityPipeline(repository=_MemoryRepository()),
        )
        targets = [ScanTarget("binance", "BTC/USDT", MarketType.PERPETUAL), ScanTarget("binance", "ETH/USDT", MarketType.PERPETUAL)]

        first = await service.run_once(targets)
        second = await service.run_once(targets)

        assert len(first["opened"]) == 1
        assert first["opened"][0].status == "opened"
        assert len(second["opened"]) == 1
        assert second["opened"][0].status == "opened"
        assert {position.symbol for position in second["active"]} == {"BTC/USDT", "ETH/USDT"}

    async def test_service_closes_position_when_monitor_detects_naked_leg(self) -> None:
        spot_client = _Client(
            orders=[_order(exchange="binance", symbol="BTC/USDT", market_type=MarketType.SPOT, side=Side.SELL, order_id="spot-close", status=OrderStatus.FILLED)],
            fetched_orders=[_order(exchange="binance", symbol="BTC/USDT", market_type=MarketType.SPOT, side=Side.SELL, order_id="spot-close", status=OrderStatus.FILLED)],
        )
        perp_client = _Client(
            orders=[_order(exchange="binance", symbol="BTC/USDT", market_type=MarketType.PERPETUAL, side=Side.BUY, order_id="perp-close", status=OrderStatus.FILLED, reduce_only=True)],
            fetched_orders=[_order(exchange="binance", symbol="BTC/USDT", market_type=MarketType.PERPETUAL, side=Side.BUY, order_id="perp-close", status=OrderStatus.FILLED, reduce_only=True)],
        )
        scanner = _SequenceScanner(
            [
                {
                    "snapshots": [
                        {
                            **build_market_snapshot("binance", "BTC/USDT", rate="0.0005").to_dict(),
                            "view": {
                                "spot_ticker": {"ask": "100"},
                                "perp_ticker": {"bid": "100.1"},
                            },
                        }
                    ],
                    "opportunities": [],
                    "output": [],
                }
            ]
        )
        repository = _MemoryRepository()
        service = FundingArbService(
            scanner=scanner,
            open_workflow=OpenPositionWorkflow(executor=PairExecutor(tracker=OrderTracker(max_polls=1, poll_interval=0, sleep=_sleep))),
            close_workflow=ClosePositionWorkflow(executor=PairExecutor(tracker=OrderTracker(max_polls=1, poll_interval=0, sleep=_sleep))),
            venues={"binance": VenueClients(exchange="binance", spot_client=spot_client, perp_client=perp_client)},
            manager=LiveExchangeManager({}),
            pipeline=OpportunityPipeline(repository=repository),
        )
        service.active_positions["funding_spot_perp:binance:BTC/USDT"] = ActiveFundingArb(
            workflow_id="funding_spot_perp:binance:BTC/USDT",
            exchange="binance",
            symbol="BTC/USDT",
            quantity=Decimal("1"),
            spot_quantity=Decimal("1"),
            perp_quantity=Decimal("0.8"),
            opened_at=datetime.now(tz=timezone.utc),
        )

        result = await service.run_once([ScanTarget("binance", "BTC/USDT", MarketType.PERPETUAL)])

        assert len(result["closed"]) == 1
        assert result["closed"][0].reason == "naked_leg"
        assert [item["status"] for item in repository.workflow_states] == ["closing", "closed"]
        assert repository.workflow_states[-1]["payload"]["alerts"] == [
            {"reason": "naked_leg", "severity": "high"}
        ]

    async def test_service_records_warning_alerts_in_workflow_state(self) -> None:
        scanner = _SequenceScanner(
            [
                {
                    "snapshots": [
                        {
                            **build_market_snapshot("binance", "BTC/USDT", rate="0.0008").to_dict(),
                            "view": {
                                "spot_ticker": {"ask": "100"},
                                "perp_ticker": {"bid": "101"},
                            },
                        }
                    ],
                    "opportunities": [],
                    "output": [],
                },
                {
                    "snapshots": [
                        {
                            **build_market_snapshot("binance", "BTC/USDT", rate="0.0008").to_dict(),
                            "view": {
                                "spot_ticker": {"ask": "100"},
                                "perp_ticker": {"bid": "100.1"},
                            },
                        }
                    ],
                    "opportunities": [],
                    "output": [],
                },
            ]
        )
        repository = _MemoryRepository()
        service = FundingArbService(
            scanner=scanner,
            open_workflow=OpenPositionWorkflow(executor=PairExecutor(tracker=OrderTracker(max_polls=1, poll_interval=0, sleep=_sleep))),
            close_workflow=ClosePositionWorkflow(executor=PairExecutor(tracker=OrderTracker(max_polls=1, poll_interval=0, sleep=_sleep))),
            venues={},
            manager=LiveExchangeManager({}),
            pipeline=OpportunityPipeline(repository=repository),
        )
        workflow_id = "funding_spot_perp:binance:BTC/USDT"
        service.active_positions[workflow_id] = ActiveFundingArb(
            workflow_id=workflow_id,
            exchange="binance",
            symbol="BTC/USDT",
            quantity=Decimal("1"),
            spot_quantity=Decimal("1"),
            perp_quantity=Decimal("1"),
            opened_at=datetime.now(tz=timezone.utc),
        )

        first = await service.run_once([ScanTarget("binance", "BTC/USDT", MarketType.PERPETUAL)])
        second = await service.run_once([ScanTarget("binance", "BTC/USDT", MarketType.PERPETUAL)])

        assert first["closed"] == []
        assert second["closed"] == []
        assert [item["status"] for item in repository.workflow_states] == ["warning", "open"]
        assert repository.workflow_states[0]["payload"] == {
            "opened_at": service.active_positions[workflow_id].opened_at.isoformat(),
            "alert_count": 1,
            "alerts": [{"reason": "basis_out_of_range", "severity": "medium"}],
        }
        assert repository.workflow_states[1]["payload"] == {
            "opened_at": service.active_positions[workflow_id].opened_at.isoformat(),
            "alert_count": 0,
            "alerts": [],
        }

    async def test_service_uses_strategy_threshold_interval_for_open_decisions(self) -> None:
        spot_client = _Client(
            orders=[_order(exchange="binance", symbol="BTC/USDT", market_type=MarketType.SPOT, side=Side.BUY, order_id="spot-open", status=OrderStatus.FILLED)],
            fetched_orders=[_order(exchange="binance", symbol="BTC/USDT", market_type=MarketType.SPOT, side=Side.BUY, order_id="spot-open", status=OrderStatus.FILLED)],
        )
        perp_client = _Client(
            orders=[_order(exchange="binance", symbol="BTC/USDT", market_type=MarketType.PERPETUAL, side=Side.SELL, order_id="perp-open", status=OrderStatus.FILLED)],
            fetched_orders=[_order(exchange="binance", symbol="BTC/USDT", market_type=MarketType.PERPETUAL, side=Side.SELL, order_id="perp-open", status=OrderStatus.FILLED)],
        )
        strategy = SpotPerpStrategy(min_open_funding_rate=Decimal("0.00015"), threshold_interval_hours=1)
        scanner = _SequenceScanner(
            [
                {
                    "snapshots": [build_market_snapshot("binance", "BTC/USDT", rate="0.0002", funding_interval_hours=1)],
                    "opportunities": [_opportunity("binance", "BTC/USDT", "0.0002", interval_hours=1)],
                    "output": [],
                }
            ]
        )
        service = FundingArbService(
            scanner=scanner,
            open_workflow=OpenPositionWorkflow(
                strategy=strategy,
                executor=PairExecutor(tracker=OrderTracker(max_polls=1, poll_interval=0, sleep=_sleep)),
            ),
            close_workflow=ClosePositionWorkflow(executor=PairExecutor(tracker=OrderTracker(max_polls=1, poll_interval=0, sleep=_sleep))),
            venues={"binance": VenueClients(exchange="binance", spot_client=spot_client, perp_client=perp_client)},
            manager=LiveExchangeManager({}),
            pipeline=OpportunityPipeline(),
            strategy=strategy,
        )

        result = await service.run_once([ScanTarget("binance", "BTC/USDT", MarketType.PERPETUAL)])

        assert len(result["opened"]) == 1
        assert result["opened"][0].status == "opened"
