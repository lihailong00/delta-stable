from __future__ import annotations
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from arb.models import FundingRate, MarketType, Order, OrderBook, OrderBookLevel, OrderStatus, Position, PositionDirection, Side, Ticker

class TestModelSerialization:

    def test_ticker_serializes_to_dict(self) -> None:
        ticker = Ticker(exchange='binance', symbol='BTC/USDT', market_type=MarketType.SPOT, bid=Decimal('100'), ask=Decimal('101'), last=Decimal('100.5'))
        payload = ticker.to_dict()
        assert payload['exchange'] == 'binance'
        assert payload['symbol'] == 'BTC/USDT'
        assert payload['market_type'] == MarketType.SPOT

    def test_orderbook_serializes_levels(self) -> None:
        book = OrderBook(exchange='okx', symbol='ETH/USDT', market_type=MarketType.PERPETUAL, bids=(OrderBookLevel(price=Decimal('10'), size=Decimal('2')),), asks=(OrderBookLevel(price=Decimal('11'), size=Decimal('3')),))
        payload = book.to_dict()
        assert payload['bids'][0]['price'] == Decimal('10')
        assert payload['asks'][0]['size'] == Decimal('3')

    def test_funding_order_and_position_cover_core_fields(self) -> None:
        next_time = datetime(2026, 3, 16, 0, 0, tzinfo=timezone.utc)
        funding = FundingRate(exchange='bybit', symbol='SOL/USDT', rate=Decimal('0.0001'), predicted_rate=Decimal('0.0002'), next_funding_time=next_time)
        order = Order(exchange='gate', symbol='BTC/USDT', market_type=MarketType.PERPETUAL, side=Side.SELL, quantity=Decimal('1'), price=Decimal('101'), status=OrderStatus.NEW)
        position = Position(exchange='binance', symbol='BTC/USDT', market_type=MarketType.PERPETUAL, direction=PositionDirection.SHORT, quantity=Decimal('1'), entry_price=Decimal('100'), mark_price=Decimal('99'), unrealized_pnl=Decimal('1'))
        assert funding.to_dict()['next_funding_time'] == next_time
        assert order.to_dict()['side'] == Side.SELL
        assert position.to_dict()['direction'] == PositionDirection.SHORT
