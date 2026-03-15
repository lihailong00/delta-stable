from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.scanner.cost_model import annualize_rate, estimate_net_rate
from arb.scanner.filters import filter_opportunities
from arb.scanner.funding_scanner import FundingOpportunity, FundingScanner


class CostModelTests(unittest.TestCase):
    def test_estimate_net_rate_subtracts_all_costs(self) -> None:
        net = estimate_net_rate(
            Decimal("0.0010"),
            trading_fee_rate=Decimal("0.0002"),
            slippage_rate=Decimal("0.0001"),
            borrow_rate=Decimal("0.0001"),
            transfer_rate=Decimal("0.0001"),
        )
        self.assertEqual(net, Decimal("0.0005"))

    def test_annualize_rate_uses_three_periods_per_day(self) -> None:
        self.assertEqual(annualize_rate(Decimal("0.0010")), Decimal("1.0950"))


class FundingScannerTests(unittest.TestCase):
    def test_filter_opportunities_applies_thresholds_and_lists(self) -> None:
        opportunities = [
            FundingOpportunity(
                exchange="binance",
                symbol="BTC/USDT",
                gross_rate=Decimal("0.001"),
                net_rate=Decimal("0.0008"),
                annualized_net_rate=Decimal("0.876"),
                spread_bps=Decimal("1"),
                liquidity_usd=Decimal("200000"),
            ),
            FundingOpportunity(
                exchange="okx",
                symbol="DOGE/USDT",
                gross_rate=Decimal("0.001"),
                net_rate=Decimal("0.0002"),
                annualized_net_rate=Decimal("0.219"),
                spread_bps=Decimal("5"),
                liquidity_usd=Decimal("500"),
            ),
        ]
        filtered = filter_opportunities(
            opportunities,
            min_net_rate=Decimal("0.0005"),
            min_liquidity_usd=Decimal("1000"),
            blacklist={"DOGE/USDT"},
        )
        self.assertEqual([item.symbol for item in filtered], ["BTC/USDT"])

    def test_scanner_ranks_by_annualized_net_rate(self) -> None:
        scanner = FundingScanner(
            trading_fee_rate=Decimal("0.0001"),
            slippage_rate=Decimal("0.0001"),
            min_net_rate=Decimal("0.0001"),
            min_liquidity_usd=Decimal("1000"),
        )
        snapshots = [
            {
                "ticker": {"bid": "100", "ask": "101"},
                "funding": {"exchange": "binance", "symbol": "BTC/USDT", "rate": "0.0012"},
                "liquidity_usd": "100000",
            },
            {
                "ticker": {"bid": "50", "ask": "50.2"},
                "funding": {"exchange": "okx", "symbol": "ETH/USDT", "rate": "0.0008"},
                "liquidity_usd": "50000",
            },
            {
                "ticker": {"bid": "10", "ask": "11"},
                "funding": {"exchange": "gate", "symbol": "XRP/USDT", "rate": "0.0001"},
                "liquidity_usd": "100",
            },
        ]
        results = scanner.scan(snapshots)

        self.assertEqual([item.symbol for item in results], ["BTC/USDT", "ETH/USDT"])
        self.assertGreater(results[0].annualized_net_rate, results[1].annualized_net_rate)


if __name__ == "__main__":
    unittest.main()
