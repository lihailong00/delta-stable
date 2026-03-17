"""离线示例：告警去重和 metrics 输出。

运行：
PYTHONPATH=src uv run python examples/monitoring_alerts.py
"""

from __future__ import annotations

from decimal import Decimal

from arb.monitoring.alerts import Alert, AlertManager
from arb.monitoring.metrics import MetricsRegistry


def main() -> None:
    sent: list[Alert] = []
    alerts = AlertManager(sent.append)
    metrics = MetricsRegistry()

    first = alerts.send(Alert(key="risk:btc", message="BTC funding reversed", severity="medium"))
    second = alerts.send(Alert(key="risk:btc", message="BTC funding reversed", severity="medium"))
    metrics.increment("alerts.total")
    metrics.set_gauge("scanner.opportunities", Decimal("3"))

    print("first sent", first)
    print("second sent", second)
    print("alert records", sent)
    print("metrics", metrics.snapshot())


if __name__ == "__main__":
    main()
