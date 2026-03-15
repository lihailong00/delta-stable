from __future__ import annotations

import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.pnl.export import export_csv, export_json
from arb.pnl.ledger import PnLLedger
from arb.pnl.reports import build_daily_report


class PnLTests(unittest.TestCase):
    def test_pnl_attribution_summary(self) -> None:
        ledger = PnLLedger()
        ledger.add_entry(category="funding", amount=Decimal("10"), strategy="spot_perp", symbol="BTC/USDT")
        ledger.add_entry(category="fees", amount=Decimal("-2"), strategy="spot_perp", symbol="BTC/USDT")
        ledger.add_entry(category="borrow", amount=Decimal("-1"), strategy="spot_perp", symbol="BTC/USDT")
        summary = ledger.summarize()
        self.assertEqual(summary["funding"], Decimal("10"))
        self.assertEqual(summary["total"], Decimal("7"))

    def test_daily_report_groups_entries(self) -> None:
        ledger = PnLLedger()
        ledger.add_entry(
            category="funding",
            amount=Decimal("5"),
            strategy="cross_perp",
            symbol="ETH/USDT",
            ts=datetime(2026, 3, 16, tzinfo=timezone.utc),
        )
        ledger.add_entry(
            category="fees",
            amount=Decimal("-1"),
            strategy="cross_perp",
            symbol="ETH/USDT",
            ts=datetime(2026, 3, 16, 12, tzinfo=timezone.utc),
        )
        report = build_daily_report(ledger.entries())
        self.assertEqual(report[0]["funding"], "5")
        self.assertEqual(report[0]["total"], "4")

    def test_exporters_generate_csv_and_json(self) -> None:
        rows = [{"date": "2026-03-16", "total": "4"}]
        self.assertIn("date,total", export_csv(rows))
        self.assertEqual(export_json(rows), '[{"date":"2026-03-16","total":"4"}]')


if __name__ == "__main__":
    unittest.main()
