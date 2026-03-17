from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.risk.position_monitor import PositionMonitor


class TestPositionMonitor:
    def test_monitor_keeps_balanced_position_open(self) -> None:
        monitor = PositionMonitor()
        decision = monitor.evaluate(
            symbol="BTC/USDT",
            snapshot={
                "ticker": {"bid": "100", "ask": "100.2", "last": "100.1"},
                "funding": {"rate": "0.0008"},
                "view": {"spot_ticker": {"ask": "100"}, "perp_ticker": {"bid": "100.1"}},
            },
            spot_quantity=Decimal("1"),
            perp_quantity=Decimal("1"),
            opened_at=datetime.now(tz=timezone.utc) - timedelta(minutes=5),
            max_holding_period=timedelta(hours=8),
            min_expected_rate=Decimal("0.0001"),
        )

        assert decision.should_close is False
        assert decision.alerts == []

    def test_monitor_closes_on_naked_leg(self) -> None:
        monitor = PositionMonitor(max_basis_bps=Decimal("10"), naked_tolerance=Decimal("0.01"))
        decision = monitor.evaluate(
            symbol="BTC/USDT",
            snapshot={
                "ticker": {"bid": "100", "ask": "100.2", "last": "100.1"},
                "funding": {"rate": "0.0008"},
                "view": {"spot_ticker": {"ask": "100"}, "perp_ticker": {"bid": "101"}},
            },
            spot_quantity=Decimal("1"),
            perp_quantity=Decimal("0.8"),
            opened_at=datetime.now(tz=timezone.utc) - timedelta(minutes=5),
            max_holding_period=timedelta(hours=8),
            min_expected_rate=Decimal("0.0001"),
        )

        assert decision.should_close is True
        assert decision.close_reason == "naked_leg"

    def test_monitor_normalizes_funding_rate_before_reversal_check(self) -> None:
        monitor = PositionMonitor()
        decision = monitor.evaluate(
            symbol="BTC/USDT",
            snapshot={
                "ticker": {"bid": "100", "ask": "100.2", "last": "100.1"},
                "funding": {"rate": "0.0008"},
            },
            spot_quantity=Decimal("1"),
            perp_quantity=Decimal("1"),
            opened_at=datetime.now(tz=timezone.utc) - timedelta(minutes=5),
            max_holding_period=timedelta(hours=8),
            min_expected_rate=Decimal("0.0002"),
            funding_interval_hours=8,
            comparison_interval_hours=1,
        )

        assert decision.should_close is True
        assert decision.close_reason == "funding_reversal"
