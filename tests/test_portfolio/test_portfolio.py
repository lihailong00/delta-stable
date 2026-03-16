from __future__ import annotations
import sys
from decimal import Decimal
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from arb.models import MarketType, Position, PositionDirection
from arb.portfolio.allocator import CapitalAllocator
from arb.portfolio.balances import BalanceBook
from arb.portfolio.positions import PositionBook

class TestPositionBook:

    def test_net_exposure_and_balance_checks(self) -> None:
        book = PositionBook()
        book.add(Position(exchange='binance', symbol='BTC/USDT', market_type=MarketType.SPOT, direction=PositionDirection.LONG, quantity=Decimal('1'), entry_price=Decimal('100'), mark_price=Decimal('100')))
        book.add(Position(exchange='okx', symbol='BTC/USDT', market_type=MarketType.PERPETUAL, direction=PositionDirection.SHORT, quantity=Decimal('0.98'), entry_price=Decimal('100'), mark_price=Decimal('100')))
        assert book.net_exposure_by_symbol()['BTC/USDT'] == Decimal('0.02')
        assert not book.is_balanced('BTC/USDT', tolerance=Decimal('0.01'))

class TestBalanceBook:

    def test_available_margin_reflects_reserved_funds(self) -> None:
        balances = BalanceBook()
        balances.set_balance('binance', 'USDT', Decimal('1000'))
        balances.reserve('binance', 'USDT', Decimal('250'))
        assert balances.total_balance(exchange='binance') == Decimal('1000')
        assert balances.available_margin('binance', 'USDT') == Decimal('750')

class TestCapitalAllocator:

    def test_allocator_applies_symbol_exchange_and_total_limits(self) -> None:
        allocator = CapitalAllocator(max_per_symbol=Decimal('500'), max_per_exchange=Decimal('800'), max_total=Decimal('1000'))
        decision = allocator.allocate(exchange='okx', symbol='ETH/USDT', requested_notional=Decimal('400'), current_symbol_notional=Decimal('200'), current_exchange_notional=Decimal('300'), current_total_notional=Decimal('700'))
        assert decision.allocated_notional == Decimal('300')
        assert decision.constrained_by == 'symbol_limit'
