"""Metrics registry."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal


class MetricsRegistry:
    """Minimal in-memory counter/gauge registry."""

    def __init__(self) -> None:
        self._counters: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        self._gauges: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))

    def increment(self, name: str, value: Decimal = Decimal("1")) -> None:
        self._counters[name] += value

    def set_gauge(self, name: str, value: Decimal) -> None:
        self._gauges[name] = value

    def snapshot(self) -> dict[str, str]:
        metrics = {}
        metrics.update({f"counter.{name}": str(value) for name, value in self._counters.items()})
        metrics.update({f"gauge.{name}": str(value) for name, value in self._gauges.items()})
        return metrics
