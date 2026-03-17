from __future__ import annotations

import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from arb.exchange.base import BaseExchangeClient
from arb.models import Fill, FundingRate, MarketType, Order, OrderBook, OrderBookLevel, OrderStatus, Position, PositionDirection, Side, Ticker
from arb.utils.symbols import exchange_symbol, normalize_symbol

class _DummyExchange(BaseExchangeClient):

    def __init__(self) -> None:
        super().__init__('dummy')

    def sign_request(self, method: str, path: str, *, query: str='', body: str='', timestamp: str | None=None) -> dict[str, str]:
        return {'X-Test-Signature': f"{method}:{path}:{timestamp or 'auto'}"}

    def to_exchange_symbol(self, symbol: str, market_type: MarketType=MarketType.SPOT) -> str:
        return exchange_symbol(symbol, delimiter='_')

    def from_exchange_symbol(self, symbol: str, market_type: MarketType=MarketType.SPOT) -> str:
        return normalize_symbol(symbol)

    async def fetch_ticker(self, symbol: str, market_type: MarketType) -> Ticker:
        return Ticker(exchange=self.name, symbol=symbol, market_type=market_type, bid=Decimal('100'), ask=Decimal('101'), last=Decimal('100.5'))

    async def fetch_orderbook(self, symbol: str, market_type: MarketType, limit: int=20) -> OrderBook:
        return OrderBook(exchange=self.name, symbol=symbol, market_type=market_type, bids=(OrderBookLevel(price=Decimal('100'), size=Decimal('1')),), asks=(OrderBookLevel(price=Decimal('101'), size=Decimal('1')),))

    async def fetch_funding_rate(self, symbol: str) -> FundingRate:
        return FundingRate(exchange=self.name, symbol=symbol, rate=Decimal('0.0001'), next_funding_time=datetime(2026, 3, 16, tzinfo=timezone.utc))

    async def fetch_balances(self) -> dict[str, Decimal]:
        return {'USDT': Decimal('1000')}

    async def create_order(self, symbol: str, market_type: MarketType, side: str, quantity: Decimal, *, price: Decimal | None=None, reduce_only: bool=False) -> Order:
        return Order(exchange=self.name, symbol=symbol, market_type=market_type, side=Side(side), quantity=quantity, price=price, status=OrderStatus.NEW, order_id='created')

    async def cancel_order(self, order_id: str, symbol: str, market_type: MarketType) -> Order:
        return Order(exchange=self.name, symbol=symbol, market_type=market_type, side=Side.BUY, quantity=Decimal('1'), price=Decimal('100'), status=OrderStatus.CANCELED, order_id=order_id)

    async def fetch_order(self, order_id: str, symbol: str, market_type: MarketType) -> Order:
        return Order(exchange=self.name, symbol=symbol, market_type=market_type, side=Side.BUY, quantity=Decimal('1'), price=Decimal('100'), status=OrderStatus.FILLED, order_id=order_id, filled_quantity=Decimal('1'))

    async def fetch_open_orders(self, symbol: str | None, market_type: MarketType) -> list[Order]:
        target = symbol or 'BTC/USDT'
        return [Order(exchange=self.name, symbol=target, market_type=market_type, side=Side.BUY, quantity=Decimal('1'), price=Decimal('100'), status=OrderStatus.NEW, order_id='open-1')]

    async def fetch_positions(self, market_type: MarketType=MarketType.PERPETUAL, *, symbol: str | None=None) -> list[Position]:
        return [Position(exchange=self.name, symbol=symbol or 'BTC/USDT', market_type=market_type, direction=PositionDirection.LONG, quantity=Decimal('1'), entry_price=Decimal('100'), mark_price=Decimal('101'))]

    async def fetch_fills(self, order_id: str, symbol: str, market_type: MarketType) -> list[Fill]:
        return [Fill(exchange=self.name, symbol=symbol, market_type=market_type, side=Side.BUY, quantity=Decimal('1'), price=Decimal('100'), order_id=order_id, fill_id='fill-1')]

class _IncompleteExchange(BaseExchangeClient):
    pass

class TestBaseExchangeClient:

    def test_abstract_exchange_requires_methods(self) -> None:
        with pytest.raises(TypeError):
            _IncompleteExchange('broken')

    @pytest.mark.asyncio
    async def test_dummy_exchange_contract(self) -> None:
        client = _DummyExchange()
        request = client.build_request('GET', '/ping', timestamp='123')
        ticker = await client.fetch_ticker('BTC/USDT', MarketType.SPOT)
        balances = await client.fetch_balances()
        batch = await client.fetch_many_tickers(['BTC/USDT', 'ETH/USDT'], MarketType.SPOT)
        order = await client.fetch_order('created', 'BTC/USDT', MarketType.SPOT)
        open_orders = await client.fetch_open_orders('BTC/USDT', MarketType.SPOT)
        positions = await client.fetch_positions(symbol='BTC/USDT')
        fills = await client.fetch_fills('created', 'BTC/USDT', MarketType.SPOT)
        assert request['headers']['X-Test-Signature'] == 'GET:/ping:123'
        assert client.to_exchange_symbol('BTC/USDT') == 'BTC_USDT'
        assert client.from_exchange_symbol('BTC_USDT') == 'BTC/USDT'
        assert ticker.exchange == 'dummy'
        assert balances['USDT'] == Decimal('1000')
        assert set(batch) == {'BTC/USDT', 'ETH/USDT'}
        assert order.status is OrderStatus.FILLED
        assert open_orders[0].order_id == 'open-1'
        assert positions[0].direction is PositionDirection.LONG
        assert fills[0].fill_id == 'fill-1'
