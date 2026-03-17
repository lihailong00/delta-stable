from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.exchange.base import BaseExchangeClient
from arb.models import Fill, FundingRate, MarketType, Order, OrderBook, OrderBookLevel, OrderStatus, Position, Side, Ticker
from arb.runtime.private_streams import PrivateStreamService
from arb.runtime.protocols import LiveRuntimeProtocol
from arb.runtime.snapshots import SnapshotService
from arb.runtime.streaming import PrivateSessionService, PublicStreamService
from arb.ws.base import BaseWebSocketClient, WsEvent

pytestmark = pytest.mark.asyncio


class _DummyExchange(BaseExchangeClient):
    def __init__(self) -> None:
        super().__init__("dummy")

    def sign_request(
        self,
        method: str,
        path: str,
        *,
        query: str = "",
        body: str = "",
        timestamp: str | None = None,
    ) -> dict[str, str]:
        return {"X-Test-Signature": "ok"}

    def to_exchange_symbol(
        self,
        symbol: str,
        market_type: MarketType = MarketType.SPOT,
    ) -> str:
        return symbol.replace("/", "")

    def from_exchange_symbol(
        self,
        symbol: str,
        market_type: MarketType = MarketType.SPOT,
    ) -> str:
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

    async def fetch_orderbook(
        self,
        symbol: str,
        market_type: MarketType,
        limit: int = 20,
    ) -> OrderBook:
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

    async def fetch_balances(self) -> dict[str, Decimal]:
        return {"USDT": Decimal("100")}

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
            exchange=self.name,
            symbol=symbol,
            market_type=market_type,
            side=Side(side.lower()),
            quantity=quantity,
            price=price,
            status=OrderStatus.NEW,
            order_id="created",
        )

    async def cancel_order(
        self,
        order_id: str,
        symbol: str,
        market_type: MarketType,
    ) -> Order:
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

    async def fetch_order(
        self,
        order_id: str,
        symbol: str,
        market_type: MarketType,
    ) -> Order:
        return Order(
            exchange=self.name,
            symbol=symbol,
            market_type=market_type,
            side=Side.BUY,
            quantity=Decimal("1"),
            price=Decimal("100"),
            status=OrderStatus.FILLED,
            order_id=order_id,
            filled_quantity=Decimal("1"),
        )

    async def fetch_open_orders(
        self,
        symbol: str | None = None,
        market_type: MarketType = MarketType.SPOT,
    ) -> tuple[Order, ...]:
        return ()

    async def fetch_positions(
        self,
        market_type: MarketType = MarketType.PERPETUAL,
        *,
        symbol: str | None = None,
    ) -> tuple[Position, ...]:
        return ()

    async def fetch_fills(
        self,
        order_id: str,
        symbol: str,
        market_type: MarketType,
    ) -> tuple[Fill, ...]:
        return (
            Fill(
                exchange=self.name,
                symbol=symbol,
                market_type=market_type,
                order_id=order_id,
                fill_id="fill-1",
                side=Side.BUY,
                quantity=Decimal("1"),
                price=Decimal("100"),
            ),
        )


class _DummyWsClient(BaseWebSocketClient):
    def __init__(self) -> None:
        super().__init__("dummy", "wss://example.test/ws")

    def build_subscribe_message(
        self,
        channel: str,
        *,
        symbol: str | None = None,
        market: str | None = None,
    ) -> dict[str, object]:
        return {"op": "subscribe", "channel": channel, "symbol": symbol}

    def parse_message(self, message: dict[str, object]) -> list[WsEvent]:
        return [
            WsEvent(
                exchange=self.exchange,
                channel=str(message.get("channel", "orderbook.update")),
                payload={"symbol": "BTC/USDT", "raw": message["value"]},
            )
        ]


class _WebSocket:
    def __init__(self, messages: list[object]) -> None:
        self.messages = list(messages)
        self.sent: list[object] = []

    async def send(self, message: object) -> None:
        self.sent.append(message)

    async def recv(self) -> object:
        return self.messages.pop(0)

    async def close(self) -> None:
        return None


class _ProtocolRuntime:
    async def public_ping(self) -> bool:
        return True

    async def validate_private_access(self) -> dict[str, str]:
        return {"USDT": "100"}

    async def fetch_public_snapshot(
        self,
        symbol: str,
        market_type: MarketType,
    ) -> dict[str, object]:
        return {"symbol": symbol, "market_type": market_type.value}


class TestRuntimeComponents:
    async def test_protocol_contract_is_runtime_checkable(self) -> None:
        runtime = _ProtocolRuntime()
        assert isinstance(runtime, LiveRuntimeProtocol)
        assert await runtime.public_ping()

    async def test_snapshot_service_collects_normalized_snapshot(self) -> None:
        service = SnapshotService("dummy", _DummyExchange())
        snapshot = await service.fetch_public_snapshot("BTC/USDT", MarketType.PERPETUAL)
        assert snapshot["ticker"]["exchange"] == "dummy"
        assert snapshot["funding"]["symbol"] == "BTC/USDT"

    async def test_public_stream_service_collects_normalized_events(self) -> None:
        socket = _WebSocket([{"value": "first"}])

        async def connector(endpoint: str) -> _WebSocket:
            assert endpoint == "wss://example.test/ws"
            return socket

        service = PublicStreamService(
            _DummyWsClient(),
            SnapshotService("dummy", _DummyExchange()),
            ws_connector=connector,
        )
        events = await service.stream("depth", symbol="BTC/USDT")
        assert socket.sent == [{"op": "subscribe", "channel": "depth", "symbol": "BTC/USDT"}]
        assert events[0]["channel"] == "orderbook.update"
        assert events[0]["payload"]["symbol"] == "BTC/USDT"

    async def test_private_session_service_runs_one_shot_subscription(self) -> None:
        socket = _WebSocket([{"event": "login", "code": "0"}])

        async def connector(endpoint: str) -> _WebSocket:
            assert endpoint == "wss://example.test/private"
            return socket

        service = PrivateSessionService("wss://example.test/private", ws_connector=connector)
        messages = await service.run({"op": "login", "args": ["token"]})
        assert socket.sent == [{"op": "login", "args": ["token"]}]
        assert messages == [{"event": "login", "code": "0"}]

    async def test_private_stream_service_collects_normalized_private_events(self) -> None:
        socket = _WebSocket([{"channel": "order.update", "value": "tracked"}])

        async def connector(endpoint: str) -> _WebSocket:
            assert endpoint == "wss://example.test/ws"
            return socket

        service = PrivateStreamService(_DummyWsClient(), ws_connector=connector)
        events = await service.stream("orders")
        assert socket.sent == [{"op": "subscribe", "channel": "orders", "symbol": None}]
        assert events[0]["exchange"] == "dummy"
        assert events[0]["channel"] == "order.update"
        assert events[0]["payload"]["symbol"] == "BTC/USDT"
