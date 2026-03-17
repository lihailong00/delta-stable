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
        assert result.funding_pnl == Decimal('0.8')
        assert result.borrow_cost == Decimal('0.2')
        assert result.open_fee_cost == Decimal('0.1')
        assert result.close_fee_cost == Decimal('0.1')
        assert len(result.equity_curve) == 2

    def test_fee_is_only_charged_on_entry_and_exit(self) -> None:
        points = load_points([
            {'ts': '2026-03-16T00:00:00+00:00', 'price': '100', 'funding_rate': '0.001', 'liquidity_usd': '100000'},
            {'ts': '2026-03-16T08:00:00+00:00', 'price': '100', 'funding_rate': '0.001', 'liquidity_usd': '100000'},
            {'ts': '2026-03-16T16:00:00+00:00', 'price': '100', 'funding_rate': '0.001', 'liquidity_usd': '100000'},
        ])

        result = FundingBacktester(fee_rate=Decimal('0.0001')).run(points, position_notional=Decimal('1000'))

        assert result.total_return == Decimal('2.8')
        assert result.equity_curve == [Decimal('0.9'), Decimal('1.9'), Decimal('2.8')]

    def test_report_is_consistent(self) -> None:
        points = load_points([{'ts': '2026-03-16T00:00:00+00:00', 'price': '100', 'funding_rate': '0.0005', 'liquidity_usd': '100000'}])
        result = FundingBacktester().run(points, position_notional=Decimal('1000'))
        report = build_backtest_report(result)
        assert report['num_points'] == 1
        assert report['total_return'] == '0.5000'
        assert report['funding_pnl'] == '0.5000'
        assert report['borrow_cost'] == '0'
        assert report['trade_count'] == 1
        assert report['holding_periods'] == 1
        assert report['capital_utilization'] == '1'

    def test_threshold_strategy_waits_opens_holds_and_closes(self) -> None:
        points = load_points([
            {'ts': '2026-03-16T00:00:00+00:00', 'price': '100', 'funding_rate': '-0.0001', 'liquidity_usd': '100000'},
            {'ts': '2026-03-16T08:00:00+00:00', 'price': '100', 'funding_rate': '0.0010', 'liquidity_usd': '100000'},
            {'ts': '2026-03-16T16:00:00+00:00', 'price': '100', 'funding_rate': '0.0008', 'liquidity_usd': '100000'},
            {'ts': '2026-03-17T00:00:00+00:00', 'price': '100', 'funding_rate': '0.00005', 'liquidity_usd': '100000'},
        ])

        result = FundingBacktester(
            open_threshold=Decimal('0.0005'),
            close_threshold=Decimal('0.0001'),
        ).run(points, position_notional=Decimal('1000'))

        assert result.total_return == Decimal('1.8')
        assert result.equity_curve == [Decimal('0'), Decimal('1.0'), Decimal('1.8'), Decimal('1.8')]
        assert result.trade_count == 1
        assert result.holding_periods == 2
        assert result.capital_utilization == Decimal('0.5')
        assert result.trades[0].net_pnl == Decimal('1.8')

    def test_threshold_strategy_uses_hysteresis_when_close_threshold_is_omitted(self) -> None:
        points = load_points([
            {'ts': '2026-03-16T00:00:00+00:00', 'price': '100', 'funding_rate': '0.0006', 'liquidity_usd': '100000'},
            {'ts': '2026-03-16T08:00:00+00:00', 'price': '100', 'funding_rate': '0.0003', 'liquidity_usd': '100000'},
            {'ts': '2026-03-16T16:00:00+00:00', 'price': '100', 'funding_rate': '0.0001', 'liquidity_usd': '100000'},
        ])

        result = FundingBacktester(
            open_threshold=Decimal('0.0005'),
            hysteresis=Decimal('0.0003'),
        ).run(points, position_notional=Decimal('1000'))

        assert result.total_return == Decimal('0.9')
        assert result.equity_curve == [Decimal('0.6'), Decimal('0.9'), Decimal('0.9')]

    def test_eventized_cost_model_splits_open_close_and_borrow_costs(self) -> None:
        points = load_points([
            {'ts': '2026-03-16T00:00:00+00:00', 'price': '100', 'funding_rate': '0.0010', 'liquidity_usd': '100000'},
            {'ts': '2026-03-16T08:00:00+00:00', 'price': '101', 'funding_rate': '-0.0002', 'liquidity_usd': '100000'},
        ])

        result = FundingBacktester(
            open_fee_rate=Decimal('0.0001'),
            close_fee_rate=Decimal('0.0002'),
            borrow_rate=Decimal('0.0001'),
        ).run(points, position_notional=Decimal('1000'))

        assert result.funding_pnl == Decimal('0.8')
        assert result.open_fee_cost == Decimal('0.1')
        assert result.close_fee_cost == Decimal('0.2')
        assert result.borrow_cost == Decimal('0.2')
        assert result.total_return == Decimal('0.3')

    def test_rebalance_fee_is_only_charged_when_price_move_exceeds_threshold(self) -> None:
        points = load_points([
            {'ts': '2026-03-16T00:00:00+00:00', 'price': '100', 'funding_rate': '0.0010', 'liquidity_usd': '100000'},
            {'ts': '2026-03-16T08:00:00+00:00', 'price': '110', 'funding_rate': '0.0010', 'liquidity_usd': '100000'},
            {'ts': '2026-03-16T16:00:00+00:00', 'price': '111', 'funding_rate': '0.0010', 'liquidity_usd': '100000'},
        ])

        result = FundingBacktester(
            rebalance_fee_rate=Decimal('0.0002'),
            rebalance_threshold_bps=Decimal('500'),
        ).run(points, position_notional=Decimal('1000'))

        assert result.funding_pnl == Decimal('3.0')
        assert result.rebalance_fee_cost == Decimal('0.2')
        assert result.total_return == Decimal('2.8')
        assert result.trades[0].rebalance_fee_cost == Decimal('0.2')

    def test_trade_ledger_and_report_aggregate_multiple_threshold_trades(self) -> None:
        points = load_points([
            {'ts': '2026-03-16T00:00:00+00:00', 'price': '100', 'funding_rate': '0.0007', 'liquidity_usd': '100000'},
            {'ts': '2026-03-16T08:00:00+00:00', 'price': '100', 'funding_rate': '0.0006', 'liquidity_usd': '100000'},
            {'ts': '2026-03-16T16:00:00+00:00', 'price': '100', 'funding_rate': '0.00005', 'liquidity_usd': '100000'},
            {'ts': '2026-03-17T00:00:00+00:00', 'price': '100', 'funding_rate': '0.0009', 'liquidity_usd': '100000'},
            {'ts': '2026-03-17T08:00:00+00:00', 'price': '100', 'funding_rate': '0.00005', 'liquidity_usd': '100000'},
        ])

        result = FundingBacktester(
            open_threshold=Decimal('0.0005'),
            close_threshold=Decimal('0.0001'),
        ).run(points, position_notional=Decimal('1000'))
        report = build_backtest_report(result)

        assert result.trade_count == 2
        assert [trade.holding_periods for trade in result.trades] == [2, 1]
        assert result.average_trade_return == Decimal('1.1')
        assert report['trade_count'] == 2
        assert report['average_trade_return'] == '1.1000'
        assert len(report['trades']) == 2
