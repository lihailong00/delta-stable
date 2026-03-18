from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.execution.protocols import (
    CancelOrderClient,
    CreateOrderClient,
    FetchFillsClient,
    FetchOrderClient,
    supports_cancel_order,
    supports_fetch_fills,
    supports_fetch_order,
)
from arb.models import Fill, MarketType, Order, OrderStatus, Side


class _Client:
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
        return Order(
            exchange="binance",
            symbol=symbol,
            market_type=market_type,
            side=Side(side),
            quantity=quantity,
            price=price,
            status=OrderStatus.NEW,
            reduce_only=reduce_only,
            order_id="created",
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
        return Order(
            exchange="binance",
            symbol=symbol,
            market_type=market_type,
            side=Side.BUY,
            quantity=Decimal("1"),
            price=Decimal("100"),
            status=OrderStatus.FILLED,
            order_id=order_id,
            filled_quantity=Decimal("1"),
        )

    async def fetch_fills(self, order_id: str, symbol: str, market_type: MarketType) -> list[Fill]:
        return [
            Fill(
                exchange="binance",
                symbol=symbol,
                market_type=market_type,
                side=Side.BUY,
                quantity=Decimal("1"),
                price=Decimal("100"),
                order_id=order_id,
                fill_id="fill-1",
            )
        ]


class TestExecutionProtocols:
    def test_protocol_guards_accept_duck_typed_exchange_client(self) -> None:
        client = _Client()

        assert isinstance(client, CreateOrderClient)
        assert isinstance(client, CancelOrderClient)
        assert isinstance(client, FetchOrderClient)
        assert isinstance(client, FetchFillsClient)
        assert supports_cancel_order(client)
        assert supports_fetch_order(client)
        assert supports_fetch_fills(client)
