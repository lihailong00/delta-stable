from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.bootstrap import build_funding_arb_app
from arb.market.schemas import MarketSnapshot
from arb.models import MarketType, Order, OrderStatus, Side
from arb.runtime.exchange_manager import ScanTarget
from arb.workflows import VenueClients
from tests.factories import build_market_snapshot


@dataclass
class _SequenceRuntime:
    snapshots: list[MarketSnapshot]

    async def public_ping(self) -> bool:
        return True

    async def fetch_public_snapshot(self, symbol: str, market_type: MarketType) -> MarketSnapshot:
        return self.snapshots.pop(0)


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


def _filled_order(order_id: str, market_type: MarketType, side: Side, *, reduce_only: bool = False) -> Order:
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


@pytest.mark.asyncio
class TestFundingArbAppBootstrap:
    async def test_build_funding_arb_app_wires_service_repository_and_control_api(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        try:
            runtime = _SequenceRuntime(
                [
                    build_market_snapshot("binance", "BTC/USDT", rate="0.001"),
                    build_market_snapshot("binance", "BTC/USDT", rate="-0.0001"),
                ]
            )
            spot_client = _Client(
                orders=[
                    _filled_order("spot-open", MarketType.SPOT, Side.BUY),
                    _filled_order("spot-close", MarketType.SPOT, Side.SELL),
                ],
                fetched_orders=[
                    _filled_order("spot-open", MarketType.SPOT, Side.BUY),
                    _filled_order("spot-close", MarketType.SPOT, Side.SELL),
                ],
            )
            perp_client = _Client(
                orders=[
                    _filled_order("perp-open", MarketType.PERPETUAL, Side.SELL),
                    _filled_order("perp-close", MarketType.PERPETUAL, Side.BUY, reduce_only=True),
                ],
                fetched_orders=[
                    _filled_order("perp-open", MarketType.PERPETUAL, Side.SELL),
                    _filled_order("perp-close", MarketType.PERPETUAL, Side.BUY, reduce_only=True),
                ],
            )
            app = build_funding_arb_app(
                runtimes={"binance": runtime},
                venues={"binance": VenueClients(exchange="binance", spot_client=spot_client, perp_client=perp_client)},
                database_path=Path(temp_dir.name) / "arb.sqlite3",
            )

            handlers = app.cli_handlers()
            result = await handlers["funding-arb-dry-run"](
                {
                    "command": "funding-arb-dry-run",
                    "exchange": ["binance"],
                    "symbol": ["BTC/USDT"],
                    "market_type": "perpetual",
                    "iterations": 2,
                }
            )

            assert result["iterations"] == 2
            assert len(result["results"][0]["opened"]) == 1
            assert len(result["results"][1]["closed"]) == 1
            assert app.control_api.strategies("secret-token")[0]["name"] == "funding_spot_perp"
            assert len(app.control_api.orders("secret-token")) == 4
        finally:
            temp_dir.cleanup()
