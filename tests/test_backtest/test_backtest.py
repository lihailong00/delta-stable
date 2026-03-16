from __future__ import annotations
import sys
from decimal import Decimal
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from arb.backtest.loader import load_points
from arb.backtest.report import build_backtest_report
from arb.backtest.simulator import FundingBacktester

class TestBacktest:

    def test_loader_parses_historical_rows(self) -> None:
        points = load_points([{'ts': '2026-03-16T00:00:00+00:00', 'price': '100', 'funding_rate': '0.0005', 'liquidity_usd': '100000'}])
        assert points[0].price == Decimal('100')
        assert points[0].funding_rate == Decimal('0.0005')

    def test_backtest_replays_strategy(self) -> None:
        points = load_points([{'ts': '2026-03-16T00:00:00+00:00', 'price': '100', 'funding_rate': '0.001', 'liquidity_usd': '100000'}, {'ts': '2026-03-16T08:00:00+00:00', 'price': '101', 'funding_rate': '-0.0002', 'liquidity_usd': '80000'}])
        result = FundingBacktester(fee_rate=Decimal('0.0001'), borrow_rate=Decimal('0.0001')).run(points, position_notional=Decimal('1000'))
        assert result.total_return == Decimal('0.4')
        assert len(result.equity_curve) == 2

    def test_report_is_consistent(self) -> None:
        points = load_points([{'ts': '2026-03-16T00:00:00+00:00', 'price': '100', 'funding_rate': '0.0005', 'liquidity_usd': '100000'}])
        result = FundingBacktester().run(points, position_notional=Decimal('1000'))
        report = build_backtest_report(result)
        assert report['num_points'] == 1
        assert report['total_return'] == '0.5000'
