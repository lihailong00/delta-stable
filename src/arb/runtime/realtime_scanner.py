"""Realtime snapshot scanner loop."""

from __future__ import annotations

import asyncio
from typing import Any

from arb.runtime.exchange_manager import LiveExchangeManager, ScanTarget
from arb.runtime.pipeline import OpportunityPipeline
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
        sleep: Any | None = None,
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
    ) -> dict[str, Any]:
        snapshots = await self.manager.collect_snapshots(targets)
        opportunities = self.scanner.scan(snapshots)
        output = self.pipeline.process(snapshots, opportunities, dry_run=dry_run)
        return {
            "snapshots": snapshots,
            "opportunities": opportunities,
            "output": output,
        }

    async def run(
        self,
        targets: list[ScanTarget],
        *,
        iterations: int | None = None,
        dry_run: bool = False,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        count = 0
        while iterations is None or count < iterations:
            results.append(await self.scan_once(targets, dry_run=dry_run))
            count += 1
            if iterations is None or count < iterations:
                await self.sleep(self.interval)
        return results
