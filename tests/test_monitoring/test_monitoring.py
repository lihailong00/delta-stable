from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.monitoring.alerts import Alert, AlertManager
from arb.monitoring.health import HealthChecker
from arb.monitoring.metrics import MetricsRegistry


class AlertManagerTests(unittest.TestCase):
    def test_alert_deduplication(self) -> None:
        sent: list[str] = []
        manager = AlertManager(lambda alert: sent.append(alert.message), dedupe_window=timedelta(minutes=5))
        now = datetime(2026, 3, 16, tzinfo=timezone.utc)
        alert = Alert(key="api_down", message="API down", severity="high")
        self.assertTrue(manager.send(alert, now=now))
        self.assertFalse(manager.send(alert, now=now + timedelta(minutes=1)))
        self.assertTrue(manager.send(alert, now=now + timedelta(minutes=6)))
        self.assertEqual(sent, ["API down", "API down"])


class HealthCheckerTests(unittest.TestCase):
    def test_connection_alerts_when_component_stale(self) -> None:
        checker = HealthChecker(max_staleness=timedelta(seconds=30))
        now = datetime(2026, 3, 16, tzinfo=timezone.utc)
        checker.heartbeat("ws.binance", at=now)
        unhealthy = checker.unhealthy_components(now=now + timedelta(seconds=31))
        self.assertEqual(unhealthy, ["ws.binance"])


class MetricsRegistryTests(unittest.TestCase):
    def test_metrics_output_contains_counters_and_gauges(self) -> None:
        registry = MetricsRegistry()
        registry.increment("orders_submitted", Decimal("2"))
        registry.set_gauge("net_exposure_btc", Decimal("0.1"))
        snapshot = registry.snapshot()
        self.assertEqual(snapshot["counter.orders_submitted"], "2")
        self.assertEqual(snapshot["gauge.net_exposure_btc"], "0.1")


if __name__ == "__main__":
    unittest.main()
