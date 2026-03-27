from __future__ import annotations
import sys
from decimal import Decimal
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from arb.scanner.cost_model import annualize_rate, daily_rate, estimate_net_rate, hourly_rate, normalize_rate, periods_per_day
from arb.scanner.filters import filter_opportunities
from arb.scanner.funding_scanner import FundingOpportunity, FundingScanner

class TestCostModel:

    def test_estimate_net_rate_subtracts_all_costs(self) -> None:
        net = estimate_net_rate(Decimal('0.0010'), trading_fee_rate=Decimal('0.0002'), slippage_rate=Decimal('0.0001'), borrow_rate=Decimal('0.0001'), transfer_rate=Decimal('0.0001'))
        assert net == Decimal('0.0005')

    def test_annualize_rate_uses_dynamic_interval_hours(self) -> None:
        assert periods_per_day() == Decimal('3')
        assert hourly_rate(Decimal('0.0010'), interval_hours=4) == Decimal('0.00025')
        assert daily_rate(Decimal('0.0010'), interval_hours=4) == Decimal('0.00600')
        assert annualize_rate(Decimal('0.0010')) == Decimal('1.0950')
        assert annualize_rate(Decimal('0.0010'), interval_hours=4) == Decimal('2.19000')
        assert normalize_rate(Decimal('0.0008'), from_interval_hours=8, to_interval_hours=1) == Decimal('0.0001')

class TestFundingScanner:

    def test_filter_opportunities_applies_thresholds_and_lists(self) -> None:
        opportunities = [FundingOpportunity(exchange='binance', symbol='BTC/USDT', gross_rate=Decimal('0.001'), net_rate=Decimal('0.0008'), funding_interval_hours=8, hourly_net_rate=Decimal('0.0001'), daily_net_rate=Decimal('0.0024'), annualized_net_rate=Decimal('0.876'), spread_bps=Decimal('1'), liquidity_usd=Decimal('200000')), FundingOpportunity(exchange='okx', symbol='DOGE/USDT', gross_rate=Decimal('0.001'), net_rate=Decimal('0.0002'), funding_interval_hours=8, hourly_net_rate=Decimal('0.000025'), daily_net_rate=Decimal('0.0006'), annualized_net_rate=Decimal('0.219'), spread_bps=Decimal('5'), liquidity_usd=Decimal('500'))]
        filtered = filter_opportunities(opportunities, min_net_rate=Decimal('0.0005'), min_liquidity_usd=Decimal('1000'), blacklist={'DOGE/USDT'})
        assert [item.symbol for item in filtered] == ['BTC/USDT']

    def test_scanner_ranks_by_annualized_net_rate(self) -> None:
        scanner = FundingScanner(trading_fee_rate=Decimal('0.0001'), slippage_rate=Decimal('0.0001'), min_net_rate=Decimal('0.0001'), min_liquidity_usd=Decimal('1000'))
        snapshots = [{'ticker': {'bid': '100', 'ask': '101'}, 'funding': {'exchange': 'binance', 'symbol': 'BTC/USDT', 'rate': '0.0012', 'funding_interval_hours': 8}, 'liquidity_usd': '100000'}, {'ticker': {'bid': '50', 'ask': '50.2'}, 'funding': {'exchange': 'okx', 'symbol': 'ETH/USDT', 'rate': '0.0008', 'funding_interval_hours': 8}, 'liquidity_usd': '50000'}, {'ticker': {'bid': '10', 'ask': '11'}, 'funding': {'exchange': 'gate', 'symbol': 'XRP/USDT', 'rate': '0.0001', 'funding_interval_hours': 8}, 'liquidity_usd': '100'}]
        results = scanner.scan(snapshots)
        assert [item.symbol for item in results] == ['BTC/USDT', 'ETH/USDT']
        assert results[0].annualized_net_rate > results[1].annualized_net_rate

    def test_scanner_compares_different_settlement_intervals_fairly(self) -> None:
        scanner = FundingScanner(trading_fee_rate=Decimal('0.00005'), slippage_rate=Decimal('0'), min_net_rate=Decimal('0.0001'), min_liquidity_usd=Decimal('1000'))
        snapshots = [
            {'ticker': {'bid': '100', 'ask': '100.1'}, 'funding': {'exchange': 'binance', 'symbol': 'BTC/USDT', 'rate': '0.0008', 'funding_interval_hours': 8}, 'liquidity_usd': '100000'},
            {'ticker': {'bid': '100', 'ask': '100.1'}, 'funding': {'exchange': 'okx', 'symbol': 'BTC/USDT', 'rate': '0.0002', 'funding_interval_hours': 1}, 'liquidity_usd': '100000'},
        ]
        results = scanner.scan(snapshots)
        assert [item.exchange for item in results] == ['okx', 'binance']
        assert results[0].funding_interval_hours == 1
        assert results[0].hourly_net_rate > results[1].hourly_net_rate

    def test_scanner_estimates_capacity_from_orderbook_depth(self) -> None:
        scanner = FundingScanner(
            min_net_rate=Decimal('0'),
            min_liquidity_usd=Decimal('0'),
            max_orderbook_levels=2,
            max_orderbook_slippage_bps=Decimal('20'),
        )
        snapshots = [
            {
                'ticker': {'bid': '100', 'ask': '100.1'},
                'funding': {'exchange': 'binance', 'symbol': 'BTC/USDT', 'rate': '0.0010', 'funding_interval_hours': 8},
                'orderbook': {
                    'exchange': 'binance',
                    'symbol': 'BTC/USDT',
                    'market_type': 'perpetual',
                    'bids': [
                        {'price': '100.0', 'size': '0.7'},
                        {'price': '99.9', 'size': '0.3'},
                    ],
                    'asks': [
                        {'price': '100.1', 'size': '0.5'},
                        {'price': '100.2', 'size': '0.5'},
                    ],
                },
            }
        ]

        results = scanner.scan(snapshots)

        assert len(results) == 1
        assert results[0].capacity_quantity == Decimal('1.0')
        assert results[0].capacity_notional_usd == Decimal('99.97')
        assert results[0].liquidity_usd == Decimal('99.97')

    def test_scanner_uses_spot_perp_view_depth_for_prices_and_capacity(self) -> None:
        scanner = FundingScanner(
            min_net_rate=Decimal('0'),
            min_liquidity_usd=Decimal('0'),
            max_orderbook_levels=2,
            max_orderbook_slippage_bps=Decimal('20'),
        )
        snapshots = [
            {
                'ticker': {'bid': '100.3', 'ask': '100.4', 'market_type': 'perpetual'},
                'funding': {'exchange': 'binance', 'symbol': 'BTC/USDT', 'rate': '0.0010', 'funding_interval_hours': 8},
                'view': {
                    'spot_ticker': {'exchange': 'binance', 'symbol': 'BTC/USDT', 'market_type': 'spot', 'bid': '99.9', 'ask': '100.0'},
                    'perp_ticker': {'exchange': 'binance', 'symbol': 'BTC/USDT', 'market_type': 'perpetual', 'bid': '100.3', 'ask': '100.4'},
                    'spot_orderbook': {
                        'exchange': 'binance',
                        'symbol': 'BTC/USDT',
                        'market_type': 'spot',
                        'bids': [{'price': '99.9', 'size': '1'}],
                        'asks': [{'price': '100.0', 'size': '0.5'}, {'price': '100.1', 'size': '0.5'}],
                    },
                    'perp_orderbook': {
                        'exchange': 'binance',
                        'symbol': 'BTC/USDT',
                        'market_type': 'perpetual',
                        'bids': [{'price': '100.3', 'size': '0.4'}, {'price': '100.2', 'size': '0.6'}],
                        'asks': [{'price': '100.4', 'size': '1'}],
                    },
                },
            }
        ]

        results = scanner.scan(snapshots)

        assert len(results) == 1
        assert results[0].capacity_quantity == Decimal('1.0')
        assert results[0].spot_entry_price == Decimal('100.05')
        assert results[0].perp_entry_price == Decimal('100.24')
        assert results[0].entry_basis_bps > Decimal('0')

    def test_scanner_filters_pair_quotes_outside_default_basis_threshold(self) -> None:
        scanner = FundingScanner(
            min_net_rate=Decimal('0'),
            min_liquidity_usd=Decimal('0'),
            max_orderbook_levels=2,
            max_orderbook_slippage_bps=Decimal('20'),
        )
        snapshots = [
            {
                'ticker': {'bid': '100.4', 'ask': '100.5', 'market_type': 'perpetual'},
                'funding': {'exchange': 'binance', 'symbol': 'BTC/USDT', 'rate': '0.0010', 'funding_interval_hours': 8},
                'view': {
                    'spot_ticker': {'exchange': 'binance', 'symbol': 'BTC/USDT', 'market_type': 'spot', 'bid': '99.9', 'ask': '100.0'},
                    'perp_ticker': {'exchange': 'binance', 'symbol': 'BTC/USDT', 'market_type': 'perpetual', 'bid': '100.4', 'ask': '100.5'},
                    'spot_orderbook': {
                        'exchange': 'binance',
                        'symbol': 'BTC/USDT',
                        'market_type': 'spot',
                        'bids': [{'price': '99.9', 'size': '1'}],
                        'asks': [{'price': '100.0', 'size': '0.5'}, {'price': '100.1', 'size': '0.5'}],
                    },
                    'perp_orderbook': {
                        'exchange': 'binance',
                        'symbol': 'BTC/USDT',
                        'market_type': 'perpetual',
                        'bids': [{'price': '100.4', 'size': '0.4'}, {'price': '100.3', 'size': '0.6'}],
                        'asks': [{'price': '100.5', 'size': '1'}],
                    },
                },
            }
        ]

        assert scanner.scan(snapshots) == []
