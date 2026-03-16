from __future__ import annotations
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from arb.monitoring.alerts import Alert, AlertManager
from arb.monitoring.health import HealthChecker
from arb.monitoring.metrics import MetricsRegistry

class TestAlertManager:

    def test_alert_deduplication(self) -> None:
        sent: list[str] = []
        manager = AlertManager(lambda alert: sent.append(alert.message), dedupe_window=timedelta(minutes=5))
        now = datetime(2026, 3, 16, tzinfo=timezone.utc)
        alert = Alert(key='api_down', message='API down', severity='high')
        assert manager.send(alert, now=now)
        assert not manager.send(alert, now=now + timedelta(minutes=1))
        assert manager.send(alert, now=now + timedelta(minutes=6))
        assert sent == ['API down', 'API down']

class TestHealthChecker:

    def test_connection_alerts_when_component_stale(self) -> None:
        checker = HealthChecker(max_staleness=timedelta(seconds=30))
        now = datetime(2026, 3, 16, tzinfo=timezone.utc)
        checker.heartbeat('ws.binance', at=now)
        unhealthy = checker.unhealthy_components(now=now + timedelta(seconds=31))
        assert unhealthy == ['ws.binance']

class TestMetricsRegistry:

    def test_metrics_output_contains_counters_and_gauges(self) -> None:
        registry = MetricsRegistry()
        registry.increment('orders_submitted', Decimal('2'))
        registry.set_gauge('net_exposure_btc', Decimal('0.1'))
        snapshot = registry.snapshot()
        assert snapshot['counter.orders_submitted'] == '2'
        assert snapshot['gauge.net_exposure_btc'] == '0.1'
