"""Manage multiple live exchange runtimes."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass

from arb.market.schemas import MarketSnapshot
from arb.models import MarketType
from arb.monitoring.alerts import Alert, AlertManager
from arb.monitoring.health import HealthChecker
from arb.runtime.protocols import SnapshotRuntimeProtocol


@dataclass(slots=True, frozen=True)
class ScanTarget:
    exchange: str
    symbol: str
    market_type: MarketType


class LiveExchangeManager:
    """Coordinate multiple live runtimes and normalize failures."""

    def __init__(
        self,
        runtimes: Mapping[str, SnapshotRuntimeProtocol],
        *,
        health_checker: HealthChecker | None = None,
        alert_manager: AlertManager | None = None,
    ) -> None:
        self.runtimes = dict(runtimes)
        self.health_checker = health_checker or HealthChecker()
        self.alert_manager = alert_manager
        self._slots: set[str] = set()

    async def ping_all(self) -> dict[str, bool]:
        async def ping_one(
            exchange: str,
            runtime: SnapshotRuntimeProtocol,
        ) -> tuple[str, bool]:
            try:
                return exchange, bool(await runtime.public_ping())
            except Exception:
                return exchange, False

        results = await asyncio.gather(
            *(ping_one(exchange, runtime) for exchange, runtime in self.runtimes.items())
        )
        return dict(results)

    async def collect_snapshots(self, targets: list[ScanTarget]) -> list[MarketSnapshot]:
        async def collect_one(target: ScanTarget) -> MarketSnapshot | Exception:
            runtime = self.runtimes[target.exchange]
            try:
                snapshot = await runtime.fetch_public_snapshot(target.symbol, target.market_type)
            except Exception as exc:
                self._emit_failure_alert(target.exchange, target.symbol, exc)
                return exc
            self.health_checker.heartbeat(target.exchange)
            return snapshot

        results = await asyncio.gather(*(collect_one(target) for target in targets))
        return [snapshot for snapshot in results if not isinstance(snapshot, Exception)]

    def unhealthy_exchanges(self) -> list[str]:
        return self.health_checker.unhealthy_components()

    def acquire_slot(self, slot: str) -> bool:
        if slot in self._slots:
            return False
        self._slots.add(slot)
        return True

    def release_slot(self, slot: str) -> None:
        self._slots.discard(slot)

    def has_slot(self, slot: str) -> bool:
        return slot in self._slots

    def _emit_failure_alert(self, exchange: str, symbol: str, error: Exception) -> None:
        if self.alert_manager is None:
            return
        self.alert_manager.send(
            Alert(
                key=f"runtime:{exchange}:{symbol}",
                message=f"{exchange} snapshot failed for {symbol}: {error}",
                severity="error",
            )
        )
