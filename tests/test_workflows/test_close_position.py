from __future__ import annotations

import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.execution.executor import PairExecutor
from arb.execution.order_tracker import OrderTracker
from arb.execution.router import RouteDecision
from arb.models import MarketType, Order, OrderStatus, Side
from arb.risk.killswitch import KillSwitch
from arb.workflows.components import RoutePlanningRequest
from arb.workflows.close_position import ClosePositionRequest, ClosePositionWorkflow
from arb.workflows.open_position import VenueClients


async def _sleep(_: float) -> None:
    return None


def _order(
    *,
    exchange: str,
    market_type: MarketType,
    side: Side,
    quantity: str,
    price: str,
    order_id: str,
    status: OrderStatus,
    filled_quantity: str = "0",
    reduce_only: bool = False,
) -> Order:
    return Order(
        exchange=exchange,
        symbol="BTC/USDT",
        market_type=market_type,
        side=side,
        quantity=Decimal(quantity),
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
        if self.orders:
            return self.orders.pop(0)
        return Order(
            exchange="binance",
            symbol=symbol,
            market_type=market_type,
            side=Side(side),
            quantity=quantity,
            price=price,
            status=OrderStatus.NEW,
            order_id=f"synthetic-{len(self.submitted)}",
            reduce_only=reduce_only,
        )

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
        if self.fetched_orders:
            return self.fetched_orders.pop(0)
        return Order(
            exchange="binance",
            symbol=symbol,
            market_type=market_type,
            side=Side.BUY,
            quantity=Decimal("0"),
            price=None,
            status=OrderStatus.NEW,
            order_id=order_id,
        )

    async def fetch_fills(self, order_id: str, symbol: str, market_type: MarketType) -> tuple[()]:
        return ()


@dataclass
class _RoutePlanner:
    exchange: str
    mode: str
    calls: list[RoutePlanningRequest] = field(default_factory=list)

    def plan(self, request: RoutePlanningRequest) -> RouteDecision:
        self.calls.append(request)
        return RouteDecision(mode=self.mode, exchange=self.exchange, urgent=request.urgent)


@dataclass
class _VenueResolver:
    alias: str
    target: str

    def resolve(
        self,
        venue_clients: Mapping[str, VenueClients],
        exchange: str,
    ) -> VenueClients | None:
        normalized_exchange = self.target if exchange == self.alias else exchange
        return venue_clients.get(normalized_exchange)


def _request(*, venue: VenueClients, **kwargs: object) -> ClosePositionRequest:
    defaults: dict[str, object] = {
        "funding_rate": Decimal("-0.0001"),
        "min_expected_rate": Decimal("0"),
        "opened_at": datetime.now(tz=timezone.utc) - timedelta(days=2),
        "max_holding_period": timedelta(hours=1),
        "maker_fee_rate": Decimal("0.0001"),
        "taker_fee_rate": Decimal("0.0004"),
        "spread_bps": Decimal("5"),
        "max_slippage_bps": Decimal("10"),
    }
    defaults.update(kwargs)
    return ClosePositionRequest(
        symbol="BTC/USDT",
        spot_quantity=Decimal("1"),
        perp_quantity=Decimal("1"),
        spot_price=Decimal("100"),
        perp_price=Decimal("100.2"),
        venue_clients={venue.exchange: venue},
        preferred_exchange=venue.exchange,
        **defaults,
    )


@pytest.mark.asyncio
class TestClosePositionWorkflow:
    async def test_close_workflow_prioritizes_funding_reversal(self) -> None:
        spot_client = _Client(
            orders=[_order(exchange="binance", market_type=MarketType.SPOT, side=Side.SELL, quantity="1", price="100", order_id="spot-close", status=OrderStatus.FILLED, filled_quantity="1")],
            fetched_orders=[_order(exchange="binance", market_type=MarketType.SPOT, side=Side.SELL, quantity="1", price="100", order_id="spot-close", status=OrderStatus.FILLED, filled_quantity="1")],
        )
        perp_client = _Client(
            orders=[_order(exchange="binance", market_type=MarketType.PERPETUAL, side=Side.BUY, quantity="1", price="100.2", order_id="perp-close", status=OrderStatus.FILLED, filled_quantity="1", reduce_only=True)],
            fetched_orders=[_order(exchange="binance", market_type=MarketType.PERPETUAL, side=Side.BUY, quantity="1", price="100.2", order_id="perp-close", status=OrderStatus.FILLED, filled_quantity="1", reduce_only=True)],
        )
        venue = VenueClients(exchange="binance", spot_client=spot_client, perp_client=perp_client)
        workflow = ClosePositionWorkflow(executor=PairExecutor(tracker=OrderTracker(max_polls=1, poll_interval=0, sleep=_sleep)))

        result = await workflow.execute(_request(venue=venue))

        assert result.status == "closed"
        assert result.reason == "funding_reversal"

    async def test_close_workflow_honors_killswitch_reduce_only_mode(self) -> None:
        spot_client = _Client(
            orders=[_order(exchange="binance", market_type=MarketType.SPOT, side=Side.SELL, quantity="1", price="99.9", order_id="spot-close", status=OrderStatus.FILLED, filled_quantity="1")],
            fetched_orders=[_order(exchange="binance", market_type=MarketType.SPOT, side=Side.SELL, quantity="1", price="99.9", order_id="spot-close", status=OrderStatus.FILLED, filled_quantity="1")],
        )
        perp_client = _Client(
            orders=[_order(exchange="binance", market_type=MarketType.PERPETUAL, side=Side.BUY, quantity="1", price="100.3", order_id="perp-close", status=OrderStatus.FILLED, filled_quantity="1", reduce_only=True)],
            fetched_orders=[_order(exchange="binance", market_type=MarketType.PERPETUAL, side=Side.BUY, quantity="1", price="100.3", order_id="perp-close", status=OrderStatus.FILLED, filled_quantity="1", reduce_only=True)],
        )
        venue = VenueClients(exchange="binance", spot_client=spot_client, perp_client=perp_client)
        kill_switch = KillSwitch()
        kill_switch.enable_reduce_only("manual")
        workflow = ClosePositionWorkflow(
            executor=PairExecutor(tracker=OrderTracker(max_polls=1, poll_interval=0, sleep=_sleep)),
            kill_switch=kill_switch,
        )

        result = await workflow.execute(_request(venue=venue, funding_rate=Decimal("0.0001")))

        assert result.status == "closed"
        assert result.route is not None
        assert result.route.mode == "taker"
        assert perp_client.submitted[0]["reduce_only"] is True

    async def test_close_workflow_retries_remaining_quantity_after_failure(self) -> None:
        spot_client = _Client(
            orders=[
                _order(exchange="binance", market_type=MarketType.SPOT, side=Side.SELL, quantity="1", price="100", order_id="spot-attempt-1", status=OrderStatus.NEW),
                _order(exchange="binance", market_type=MarketType.SPOT, side=Side.SELL, quantity="1", price="99.9", order_id="spot-attempt-2", status=OrderStatus.FILLED, filled_quantity="1"),
            ],
            fetched_orders=[
                _order(exchange="binance", market_type=MarketType.SPOT, side=Side.SELL, quantity="1", price="100", order_id="spot-attempt-1", status=OrderStatus.NEW),
                _order(exchange="binance", market_type=MarketType.SPOT, side=Side.SELL, quantity="1", price="99.9", order_id="spot-attempt-2", status=OrderStatus.FILLED, filled_quantity="1"),
            ],
        )
        perp_client = _Client(
            orders=[
                _order(exchange="binance", market_type=MarketType.PERPETUAL, side=Side.BUY, quantity="1", price="100.2", order_id="perp-attempt-1", status=OrderStatus.NEW, reduce_only=True),
                _order(exchange="binance", market_type=MarketType.PERPETUAL, side=Side.BUY, quantity="1", price="100.3", order_id="perp-attempt-2", status=OrderStatus.FILLED, filled_quantity="1", reduce_only=True),
            ],
            fetched_orders=[
                _order(exchange="binance", market_type=MarketType.PERPETUAL, side=Side.BUY, quantity="1", price="100.2", order_id="perp-attempt-1", status=OrderStatus.NEW, reduce_only=True),
                _order(exchange="binance", market_type=MarketType.PERPETUAL, side=Side.BUY, quantity="1", price="100.3", order_id="perp-attempt-2", status=OrderStatus.FILLED, filled_quantity="1", reduce_only=True),
            ],
        )
        venue = VenueClients(exchange="binance", spot_client=spot_client, perp_client=perp_client)
        workflow = ClosePositionWorkflow(executor=PairExecutor(tracker=OrderTracker(max_polls=1, poll_interval=0, sleep=_sleep)))

        result = await workflow.execute(_request(venue=venue, max_retries=1))

        assert result.status == "closed"
        assert result.retries == 1
        assert spot_client.submitted[1]["price"] < spot_client.submitted[0]["price"]

    async def test_close_workflow_returns_reduced_when_partial_close_remains(self) -> None:
        spot_client = _Client(
            orders=[_order(exchange="binance", market_type=MarketType.SPOT, side=Side.SELL, quantity="1", price="100", order_id="spot-close", status=OrderStatus.NEW, filled_quantity="0")],
            fetched_orders=[_order(exchange="binance", market_type=MarketType.SPOT, side=Side.SELL, quantity="1", price="100", order_id="spot-close", status=OrderStatus.PARTIALLY_FILLED, filled_quantity="0.1")],
        )
        perp_client = _Client(
            orders=[_order(exchange="binance", market_type=MarketType.PERPETUAL, side=Side.BUY, quantity="1", price="100.2", order_id="perp-close", status=OrderStatus.NEW, filled_quantity="0", reduce_only=True)],
            fetched_orders=[_order(exchange="binance", market_type=MarketType.PERPETUAL, side=Side.BUY, quantity="1", price="100.2", order_id="perp-close", status=OrderStatus.PARTIALLY_FILLED, filled_quantity="0.1", reduce_only=True)],
        )
        venue = VenueClients(exchange="binance", spot_client=spot_client, perp_client=perp_client)
        workflow = ClosePositionWorkflow(executor=PairExecutor(tracker=OrderTracker(max_polls=1, poll_interval=0, sleep=_sleep)))

        result = await workflow.execute(_request(venue=venue, max_retries=0))

        assert result.status == "reduced"
        assert result.remaining_spot_quantity == Decimal("0.9")
        assert result.remaining_perp_quantity == Decimal("0.9")

    async def test_close_workflow_supports_injected_route_planner_and_venue_resolver(self) -> None:
        spot_client = _Client(
            orders=[_order(exchange="binance", market_type=MarketType.SPOT, side=Side.SELL, quantity="1", price="99.9", order_id="spot-close", status=OrderStatus.FILLED, filled_quantity="1")],
            fetched_orders=[_order(exchange="binance", market_type=MarketType.SPOT, side=Side.SELL, quantity="1", price="99.9", order_id="spot-close", status=OrderStatus.FILLED, filled_quantity="1")],
        )
        perp_client = _Client(
            orders=[_order(exchange="binance", market_type=MarketType.PERPETUAL, side=Side.BUY, quantity="1", price="100.3", order_id="perp-close", status=OrderStatus.FILLED, filled_quantity="1", reduce_only=True)],
            fetched_orders=[_order(exchange="binance", market_type=MarketType.PERPETUAL, side=Side.BUY, quantity="1", price="100.3", order_id="perp-close", status=OrderStatus.FILLED, filled_quantity="1", reduce_only=True)],
        )
        venue = VenueClients(exchange="binance", spot_client=spot_client, perp_client=perp_client)
        route_planner = _RoutePlanner(exchange="synthetic-binance", mode="taker")
        venue_resolver = _VenueResolver(alias="synthetic-binance", target="binance")
        workflow = ClosePositionWorkflow(
            executor=PairExecutor(tracker=OrderTracker(max_polls=1, poll_interval=0, sleep=_sleep)),
            route_planner=route_planner,
            venue_resolver=venue_resolver,
        )

        result = await workflow.execute(_request(venue=venue, max_holding_period=None))

        assert result.status == "closed"
        assert result.route is not None
        assert result.route.exchange == "synthetic-binance"
        assert result.route.mode == "taker"
        assert route_planner.calls[0].preferred_exchange == "binance"
        assert spot_client.submitted[0]["price"] < Decimal("100")
