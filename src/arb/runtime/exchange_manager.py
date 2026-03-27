"""Manage multiple live exchange runtimes."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass

from arb.market.schemas import MarketSnapshot
from arb.market.spot_perp_view import SpotPerpSnapshot
from arb.models import MarketType
from arb.monitoring.alerts import Alert, AlertManager
from arb.monitoring.health import ComponentKey, ComponentKind, HealthChecker
from arb.runtime.protocols import SnapshotRuntimeProtocol, SpotPerpSnapshotRuntimeProtocol


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
            self.health_checker.heartbeat(ComponentKey.exchange(target.exchange))
            return snapshot

        results = await asyncio.gather(*(collect_one(target) for target in targets))
        return [snapshot for snapshot in results if not isinstance(snapshot, Exception)]

    async def collect_funding_snapshots(self, targets: list[ScanTarget]) -> list[MarketSnapshot]:
        """Collect funding snapshots with spot/perp views when runtimes support them."""

        async def collect_one(target: ScanTarget) -> MarketSnapshot | Exception:
            runtime = self.runtimes[target.exchange]
            try:
                if (
                    target.market_type is MarketType.PERPETUAL
                    and isinstance(runtime, SpotPerpSnapshotRuntimeProtocol)
                ):
                    pair_snapshot = await runtime.fetch_spot_perp_snapshot(target.symbol)
                    snapshot = self._collapse_spot_perp_snapshot(pair_snapshot)
                else:
                    snapshot = await runtime.fetch_public_snapshot(target.symbol, target.market_type)
            except Exception as exc:
                self._emit_failure_alert(target.exchange, target.symbol, exc)
                return exc
            self.health_checker.heartbeat(ComponentKey.exchange(target.exchange))
            return snapshot

        results = await asyncio.gather(*(collect_one(target) for target in targets))
        return [snapshot for snapshot in results if not isinstance(snapshot, Exception)]

    def unhealthy_exchanges(self) -> list[str]:
        return [
            component.name
            for component in self.health_checker.unhealthy_components()
            if component.kind is ComponentKind.EXCHANGE
        ]

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

    @staticmethod
    def _collapse_spot_perp_snapshot(snapshot: SpotPerpSnapshot) -> MarketSnapshot:
        """Flatten a spot/perp pair into the funding pipeline's MarketSnapshot shape."""

        spot = snapshot.spot
        perp = snapshot.perp
        liquidity_candidates = [
            value for value in (spot.liquidity_usd, perp.liquidity_usd) if value is not None
        ]
        liquidity_usd = min(liquidity_candidates) if liquidity_candidates else None
        view_payload = snapshot.view.to_dict()
        if spot.orderbook is not None:
            view_payload["spot_orderbook"] = spot.orderbook.to_dict()
        if perp.orderbook is not None:
            view_payload["perp_orderbook"] = perp.orderbook.to_dict()
        return MarketSnapshot(
            ticker=perp.ticker,
            orderbook=perp.orderbook,
            funding=perp.funding,
            view=view_payload,
            liquidity_usd=liquidity_usd,
            top_ask_size=perp.top_ask_size,
        )
