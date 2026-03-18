"""Realtime snapshot scanner loop."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from arb.market.schemas import MarketSnapshot
from arb.runtime.exchange_manager import LiveExchangeManager, ScanTarget
from arb.runtime.pipeline import OpportunityPipeline
from arb.runtime.schemas import RealtimeScanResult
from arb.scanner.funding_scanner import FundingOpportunity, FundingScanner


class RealtimeScanner:
    """Run periodic multi-exchange funding scans."""

    def __init__(
        self,
        manager: LiveExchangeManager,
        scanner: FundingScanner,
        pipeline: OpportunityPipeline,
        *,
        interval: float = 1.0,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self.manager = manager
        self.scanner = scanner
        self.pipeline = pipeline
        self.interval = interval
        self.sleep = sleep or asyncio.sleep

    async def scan_once(
        self,
        targets: list[ScanTarget],
        *,
        dry_run: bool = False,
    ) -> RealtimeScanResult:
        snapshots: list[MarketSnapshot] = await self.manager.collect_snapshots(targets)
        opportunities = self.scanner.scan(snapshots)
        output = self.pipeline.process(snapshots, opportunities, dry_run=dry_run)
        return RealtimeScanResult(
            snapshots=snapshots,
            opportunities=opportunities,
            output=output,
        )

    async def run(
        self,
        targets: list[ScanTarget],
        *,
        iterations: int | None = None,
        dry_run: bool = False,
    ) -> list[RealtimeScanResult]:
        results: list[RealtimeScanResult] = []
        count = 0
        while iterations is None or count < iterations:
            results.append(await self.scan_once(targets, dry_run=dry_run))
            count += 1
            if iterations is None or count < iterations:
                await self.sleep(self.interval)
        return results

    def opportunity_key(self, opportunity: FundingOpportunity) -> str:
        return f"{opportunity.exchange}:{opportunity.symbol}"

    def select_opportunities(
        self,
        opportunities: list[FundingOpportunity],
        *,
        limit: int = 1,
        active_keys: set[str] | None = None,
    ) -> list[FundingOpportunity]:
        active = active_keys or set()
        selected: list[FundingOpportunity] = []
        for opportunity in opportunities:
            key = self.opportunity_key(opportunity)
            if key in active:
                continue
            selected.append(opportunity)
            if len(selected) >= limit:
                break
        return selected
