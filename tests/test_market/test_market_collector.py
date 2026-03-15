from __future__ import annotations

import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.exchange.base import BaseExchangeClient
from arb.market.collector import MarketDataCollector
from arb.models import FundingRate, MarketType, Order, OrderBook, OrderBookLevel, OrderStatus, Side, Ticker
from arb.ws.base import BaseWebSocketClient, WsEvent


class _DummyExchange(BaseExchangeClient):
    def __init__(self, name: str) -> None:
        super().__init__(name)

    def sign_request(self, method: str, path: str, *, query: str = "", body: str = "", timestamp: str | None = None):
        return {}

    def to_exchange_symbol(self, symbol: str, market_type: MarketType = MarketType.SPOT) -> str:
        return symbol

    def from_exchange_symbol(self, symbol: str, market_type: MarketType = MarketType.SPOT) -> str:
        return symbol

    async def fetch_ticker(self, symbol: str, market_type: MarketType) -> Ticker:
        return Ticker(
            exchange=self.name,
            symbol=symbol,
            market_type=market_type,
            bid=Decimal("100"),
            ask=Decimal("101"),
            last=Decimal("100.5"),
        )

    async def fetch_orderbook(self, symbol: str, market_type: MarketType, limit: int = 20) -> OrderBook:
        return OrderBook(
            exchange=self.name,
            symbol=symbol,
            market_type=market_type,
            bids=(OrderBookLevel(price=Decimal("100"), size=Decimal("1")),),
            asks=(OrderBookLevel(price=Decimal("101"), size=Decimal("2")),),
        )

    async def fetch_funding_rate(self, symbol: str) -> FundingRate:
        return FundingRate(
            exchange=self.name,
            symbol=symbol,
            rate=Decimal("0.0001"),
            predicted_rate=Decimal("0.0002"),
            next_funding_time=datetime(2026, 3, 16, tzinfo=timezone.utc),
        )

    async def fetch_balances(self):
        return {"USDT": Decimal("1000")}

    async def create_order(self, symbol: str, market_type: MarketType, side: str, quantity: Decimal, *, price=None, reduce_only=False) -> Order:
        return Order(
            exchange=self.name,
            symbol=symbol,
            market_type=market_type,
            side=Side(side),
            quantity=quantity,
            price=price,
            status=OrderStatus.NEW,
        )

    async def cancel_order(self, order_id: str, symbol: str, market_type: MarketType) -> Order:
        return Order(
            exchange=self.name,
            symbol=symbol,
            market_type=market_type,
            side=Side.BUY,
            quantity=Decimal("0"),
            price=None,
            status=OrderStatus.CANCELED,
            order_id=order_id,
        )


class _DummyWs(BaseWebSocketClient):
    def __init__(self) -> None:
        super().__init__("dummy", "wss://example.invalid/ws")

    def build_subscribe_message(self, channel: str, *, symbol: str | None = None, market: str | None = None):
        return {"op": "subscribe", "channel": channel, "symbol": symbol}

    def parse_message(self, message):
        return [WsEvent(exchange=self.exchange, channel="orderbook.update", payload=dict(message))]


class MarketDataCollectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_collect_snapshot_normalizes_spot_and_perpetual_data(self) -> None:
        collector = MarketDataCollector({"binance": _DummyExchange("binance")})
        spot = await collector.collect_snapshot("binance", "BTC/USDT", MarketType.SPOT)
        perp = await collector.collect_snapshot("binance", "BTC/USDT", MarketType.PERPETUAL)

        self.assertEqual(spot["ticker"]["kind"], "ticker")
        self.assertEqual(spot["orderbook"]["kind"], "orderbook")
        self.assertNotIn("funding", spot)
        self.assertEqual(perp["funding"]["kind"], "funding")
        self.assertEqual(perp["funding"]["exchange"], "binance")

    async def test_ingest_ws_message_publishes_normalized_events(self) -> None:
        collector = MarketDataCollector({"binance": _DummyExchange("binance")})
        ws = _DummyWs()
        captured: list[dict[str, object]] = []
        collector.router.subscribe("orderbook.update", lambda payload: captured.append(payload))

        events = await collector.ingest_ws_message(ws, {"symbol": "BTC/USDT"})

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "ws_event")
        self.assertEqual(captured[0]["channel"], "orderbook.update")


if __name__ == "__main__":
    unittest.main()
