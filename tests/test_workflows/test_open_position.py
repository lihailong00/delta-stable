from __future__ import annotations

import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.execution.executor import PairExecutor
from arb.execution.guards import GuardContext
from arb.execution.order_tracker import OrderTracker
from arb.execution.router import RouteDecision, RouteMode
from arb.models import MarketType, Order, OrderStatus, Side
from arb.strategy.spot_perp import SpotPerpStrategy
from arb.workflows.components import RoutePlanningRequest
from arb.workflows.open_position import OpenPositionRequest, OpenPositionWorkflow, VenueClientBundle


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


class _Clock:
    def __init__(self, *values: float) -> None:
        self.values = list(values)
        self.index = 0

    def __call__(self) -> float:
        if not self.values:
            return 0.0
        if self.index >= len(self.values):
            return self.values[-1]
        value = self.values[self.index]
        self.index += 1
        return value


@dataclass
class _RoutePlanner:
    exchange: str
    mode: RouteMode
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
        venue_clients: Mapping[str, VenueClientBundle],
        exchange: str,
    ) -> VenueClientBundle | None:
        normalized_exchange = self.target if exchange == self.alias else exchange
        return venue_clients.get(normalized_exchange)


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


def _request(*, venue: VenueClientBundle, **kwargs: object) -> OpenPositionRequest:
    defaults: dict[str, object] = {
        "funding_rate": Decimal("0.001"),
        "spot_price": Decimal("100"),
        "perp_price": Decimal("100.2"),
        "maker_fee_rate": Decimal("0.0001"),
        "taker_fee_rate": Decimal("0.0004"),
        "spread_bps": Decimal("5"),
        "max_slippage_bps": Decimal("10"),
    }
    defaults.update(kwargs)
    return OpenPositionRequest(
        symbol="BTC/USDT",
        quantity=Decimal("1"),
        venue_client_bundle={venue.exchange: venue},
        preferred_exchange=venue.exchange,
        **defaults,
    )


@pytest.mark.asyncio
class TestOpenPositionWorkflow:
    async def test_open_position_succeeds_on_initial_maker_attempt(self) -> None:
        spot_client = _Client(
            orders=[_order(exchange="binance", market_type=MarketType.SPOT, side=Side.BUY, quantity="1", price="100", order_id="spot-1", status=OrderStatus.FILLED, filled_quantity="1")],
            fetched_orders=[_order(exchange="binance", market_type=MarketType.SPOT, side=Side.BUY, quantity="1", price="100", order_id="spot-1", status=OrderStatus.FILLED, filled_quantity="1")],
        )
        perp_client = _Client(
            orders=[_order(exchange="binance", market_type=MarketType.PERPETUAL, side=Side.SELL, quantity="1", price="100.2", order_id="perp-1", status=OrderStatus.FILLED, filled_quantity="1")],
            fetched_orders=[_order(exchange="binance", market_type=MarketType.PERPETUAL, side=Side.SELL, quantity="1", price="100.2", order_id="perp-1", status=OrderStatus.FILLED, filled_quantity="1")],
        )
        venue = VenueClientBundle(
            exchange="binance",
            spot_client=spot_client,
            perp_client=perp_client,
            spot_context=GuardContext(available_balance=Decimal("1000"), max_notional=Decimal("1000"), supported_symbols={"BTC/USDT"}),
            perp_context=GuardContext(available_balance=Decimal("1000"), max_notional=Decimal("1000"), supported_symbols={"BTC/USDT"}),
        )
        workflow = OpenPositionWorkflow(
            executor=PairExecutor(tracker=OrderTracker(max_polls=1, poll_interval=0, sleep=_sleep)),
            clock=_Clock(0.0, 0.1),
        )

        result = await workflow.execute(_request(venue=venue))

        assert result.status == "opened"
        assert result.route is not None
        assert result.route.mode == "maker"
        assert result.attempts == 1
        assert spot_client.submitted[0]["price"] == Decimal("100")

    async def test_open_position_retries_with_taker_when_maker_times_out(self) -> None:
        spot_client = _Client(
            orders=[
                _order(exchange="binance", market_type=MarketType.SPOT, side=Side.BUY, quantity="1", price="100", order_id="spot-maker", status=OrderStatus.NEW),
                _order(exchange="binance", market_type=MarketType.SPOT, side=Side.BUY, quantity="1", price="100.1", order_id="spot-taker", status=OrderStatus.FILLED, filled_quantity="1"),
            ],
            fetched_orders=[
                _order(exchange="binance", market_type=MarketType.SPOT, side=Side.BUY, quantity="1", price="100", order_id="spot-maker", status=OrderStatus.NEW),
                _order(exchange="binance", market_type=MarketType.SPOT, side=Side.BUY, quantity="1", price="100.1", order_id="spot-taker", status=OrderStatus.FILLED, filled_quantity="1"),
            ],
        )
        perp_client = _Client(
            orders=[
                _order(exchange="binance", market_type=MarketType.PERPETUAL, side=Side.SELL, quantity="1", price="100.2", order_id="perp-maker", status=OrderStatus.NEW),
                _order(exchange="binance", market_type=MarketType.PERPETUAL, side=Side.SELL, quantity="1", price="100.1", order_id="perp-taker", status=OrderStatus.FILLED, filled_quantity="1"),
            ],
            fetched_orders=[
                _order(exchange="binance", market_type=MarketType.PERPETUAL, side=Side.SELL, quantity="1", price="100.2", order_id="perp-maker", status=OrderStatus.NEW),
                _order(exchange="binance", market_type=MarketType.PERPETUAL, side=Side.SELL, quantity="1", price="100.1", order_id="perp-taker", status=OrderStatus.FILLED, filled_quantity="1"),
            ],
        )
        venue = VenueClientBundle(exchange="binance", spot_client=spot_client, perp_client=perp_client)
        workflow = OpenPositionWorkflow(
            executor=PairExecutor(tracker=OrderTracker(max_polls=1, poll_interval=0, sleep=_sleep)),
            clock=_Clock(0.0, 0.2, 0.4),
        )

        result = await workflow.execute(_request(venue=venue, max_naked_seconds=1.0))

        assert result.status == "opened"
        assert result.reason == "opened_after_taker_fallback"
        assert result.route is not None
        assert result.route.mode == "taker"
        assert result.attempts == 2
        assert spot_client.submitted[1]["price"] > spot_client.submitted[0]["price"]

    async def test_open_position_rolls_back_exposure_after_naked_timeout(self) -> None:
        spot_client = _Client(
            orders=[
                _order(exchange="binance", market_type=MarketType.SPOT, side=Side.BUY, quantity="1", price="100", order_id="spot-open", status=OrderStatus.FILLED, filled_quantity="1"),
                _order(exchange="binance", market_type=MarketType.SPOT, side=Side.SELL, quantity="1", price="100", order_id="spot-rollback", status=OrderStatus.FILLED, filled_quantity="1"),
            ],
            fetched_orders=[
                _order(exchange="binance", market_type=MarketType.SPOT, side=Side.BUY, quantity="1", price="100", order_id="spot-open", status=OrderStatus.FILLED, filled_quantity="1"),
            ],
        )
        perp_client = _Client(
            orders=[
                _order(exchange="binance", market_type=MarketType.PERPETUAL, side=Side.SELL, quantity="1", price="100.2", order_id="perp-open", status=OrderStatus.NEW),
            ],
            fetched_orders=[
                _order(exchange="binance", market_type=MarketType.PERPETUAL, side=Side.SELL, quantity="1", price="100.2", order_id="perp-open", status=OrderStatus.NEW),
            ],
        )
        venue = VenueClientBundle(exchange="binance", spot_client=spot_client, perp_client=perp_client)
        workflow = OpenPositionWorkflow(
            executor=PairExecutor(tracker=OrderTracker(max_polls=1, poll_interval=0, sleep=_sleep)),
            clock=_Clock(0.0, 2.0),
        )

        result = await workflow.execute(_request(venue=venue, max_naked_seconds=1.0, allow_taker_fallback=False))

        assert result.status == "rolled_back"
        assert result.reason == "naked_time_exceeded"
        assert len(result.rollback_orders) == 1
        assert spot_client.submitted[-1]["side"] == "sell"
        assert spot_client.submitted[-1]["quantity"] == Decimal("1")

    async def test_open_position_rejects_when_normalized_funding_is_below_threshold(self) -> None:
        venue = VenueClientBundle(exchange="binance", spot_client=_Client(orders=[]), perp_client=_Client(orders=[]))
        workflow = OpenPositionWorkflow(
            strategy=SpotPerpStrategy(min_open_funding_rate=Decimal("0.0001"), threshold_interval_hours=1),
            executor=PairExecutor(tracker=OrderTracker(max_polls=1, poll_interval=0, sleep=_sleep)),
        )

        result = await workflow.execute(
            _request(
                venue=venue,
                funding_rate=Decimal("0.0006"),
                funding_interval_hours=8,
            )
        )

        assert result.status == "rejected"
        assert result.reason == "funding_below_threshold"

    async def test_open_position_supports_injected_route_planner_and_venue_resolver(self) -> None:
        spot_client = _Client(
            orders=[_order(exchange="binance", market_type=MarketType.SPOT, side=Side.BUY, quantity="1", price="100.1", order_id="spot-1", status=OrderStatus.FILLED, filled_quantity="1")],
            fetched_orders=[_order(exchange="binance", market_type=MarketType.SPOT, side=Side.BUY, quantity="1", price="100.1", order_id="spot-1", status=OrderStatus.FILLED, filled_quantity="1")],
        )
        perp_client = _Client(
            orders=[_order(exchange="binance", market_type=MarketType.PERPETUAL, side=Side.SELL, quantity="1", price="100.1", order_id="perp-1", status=OrderStatus.FILLED, filled_quantity="1")],
            fetched_orders=[_order(exchange="binance", market_type=MarketType.PERPETUAL, side=Side.SELL, quantity="1", price="100.1", order_id="perp-1", status=OrderStatus.FILLED, filled_quantity="1")],
        )
        venue = VenueClientBundle(exchange="binance", spot_client=spot_client, perp_client=perp_client)
        route_planner = _RoutePlanner(exchange="synthetic-binance", mode=RouteMode.TAKER)
        venue_resolver = _VenueResolver(alias="synthetic-binance", target="binance")
        workflow = OpenPositionWorkflow(
            executor=PairExecutor(tracker=OrderTracker(max_polls=1, poll_interval=0, sleep=_sleep)),
            route_planner=route_planner,
            venue_resolver=venue_resolver,
        )

        result = await workflow.execute(_request(venue=venue))

        assert result.status == "opened"
        assert result.route is not None
        assert result.route.exchange == "synthetic-binance"
        assert result.route.mode == "taker"
        assert route_planner.calls[0].preferred_exchange == "binance"
        assert spot_client.submitted[0]["price"] > Decimal("100")
