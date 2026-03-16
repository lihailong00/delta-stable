from __future__ import annotations
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from arb.models import FundingRate, MarketType, Order, OrderStatus, Position, PositionDirection, Side, Ticker
from arb.storage.db import Database
from arb.storage.repository import Repository

class TestRepository:

    def setup_method(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / 'arb.sqlite3'
        self.database = Database(self.db_path)
        self.database.initialize()
        self.repository = Repository(self.database)

    def teardown_method(self) -> None:
        self.temp_dir.cleanup()

    def test_initialize_creates_schema_tables(self) -> None:
        with sqlite3.connect(self.db_path) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert {'orders', 'fills', 'positions', 'funding_snapshots', 'ticks'}.issubset(tables)

    def test_save_order_and_position(self) -> None:
        order = Order(exchange='binance', symbol='BTC/USDT', market_type=MarketType.PERPETUAL, side=Side.SELL, quantity=Decimal('1'), price=Decimal('100'), status=OrderStatus.NEW, order_id='ord-1')
        position = Position(exchange='binance', symbol='BTC/USDT', market_type=MarketType.PERPETUAL, direction=PositionDirection.SHORT, quantity=Decimal('1'), entry_price=Decimal('100'), mark_price=Decimal('99'), unrealized_pnl=Decimal('1'))
        self.repository.save_order(order)
        self.repository.save_position(position)
        orders = self.repository.list_orders()
        positions = self.repository.list_positions()
        assert orders[0]['order_id'] == 'ord-1'
        assert positions[0]['direction'] == 'short'

    def test_save_funding_and_query_history(self) -> None:
        now = datetime(2026, 3, 16, tzinfo=timezone.utc)
        earlier = datetime(2026, 3, 15, tzinfo=timezone.utc)
        self.repository.save_funding(FundingRate(exchange='okx', symbol='BTC/USDT', rate=Decimal('0.0001'), predicted_rate=Decimal('0.0002'), next_funding_time=now, ts=earlier))
        self.repository.save_funding(FundingRate(exchange='okx', symbol='BTC/USDT', rate=Decimal('0.0003'), predicted_rate=Decimal('0.0004'), next_funding_time=now, ts=now))
        history = self.repository.list_funding_history(exchange='okx', symbol='BTC/USDT')
        assert len(history) == 2
        assert history[0]['rate'] == '0.0003'

    def test_save_ticker_and_fill(self) -> None:
        ticker = Ticker(exchange='gate', symbol='ETH/USDT', market_type=MarketType.SPOT, bid=Decimal('10'), ask=Decimal('11'), last=Decimal('10.5'))
        self.repository.save_ticker(ticker)
        self.repository.save_fill({'fill_id': 'fill-1', 'order_id': 'ord-1', 'exchange': 'gate', 'symbol': 'ETH/USDT', 'side': 'buy', 'quantity': '2', 'price': '10.5', 'ts': '2026-03-16T00:00:00+00:00'})
        with self.database.connect() as connection:
            tick_count = connection.execute('SELECT COUNT(*) FROM ticks').fetchone()[0]
            fill_count = connection.execute('SELECT COUNT(*) FROM fills').fetchone()[0]
        assert tick_count == 1
        assert fill_count == 1
