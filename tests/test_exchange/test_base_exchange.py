from __future__ import annotations

import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from arb.exchange.base import BaseExchangeClient
from arb.models import FundingRate, MarketType, Order, OrderBook, OrderBookLevel, OrderStatus, Side, Ticker
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
        assert request['headers']['X-Test-Signature'] == 'GET:/ping:123'
        assert client.to_exchange_symbol('BTC/USDT') == 'BTC_USDT'
        assert client.from_exchange_symbol('BTC_USDT') == 'BTC/USDT'
        assert ticker.exchange == 'dummy'
        assert balances['USDT'] == Decimal('1000')
        assert set(batch) == {'BTC/USDT', 'ETH/USDT'}
