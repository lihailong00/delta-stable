"""Persistence and output pipeline for realtime scans."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from arb.models import FundingRate, MarketType, Ticker
from arb.monitoring.metrics import MetricsRegistry
from arb.scanner.funding_scanner import FundingOpportunity
from arb.storage.repository import Repository


class OpportunityPipeline:
    """Persist normalized snapshots and publish scan output."""

    def __init__(
        self,
        *,
        repository: Repository | None = None,
        metrics: MetricsRegistry | None = None,
        publisher: Any | None = None,
    ) -> None:
        self.repository = repository
        self.metrics = metrics or MetricsRegistry()
        self.publisher = publisher

    def process(
        self,
        snapshots: list[dict[str, Any]],
        opportunities: list[FundingOpportunity],
        *,
        dry_run: bool = False,
    ) -> list[str]:
        self.persist_snapshots(snapshots)
        messages = self.publish_opportunities(opportunities, dry_run=dry_run)
        self.metrics.set_gauge("realtime.opportunity_count", Decimal(len(opportunities)))
        return messages

    def persist_snapshots(self, snapshots: list[dict[str, Any]]) -> None:
        for snapshot in snapshots:
            self.metrics.increment("realtime.snapshots")
            ticker = snapshot.get("ticker")
            if ticker and self.repository is not None:
                self.repository.save_ticker(self._to_ticker(ticker))
            funding = snapshot.get("funding")
            if funding and self.repository is not None:
                self.repository.save_funding(self._to_funding(funding))

    def publish_opportunities(
        self,
        opportunities: list[FundingOpportunity],
        *,
        dry_run: bool = False,
    ) -> list[str]:
        messages = [self.format_opportunity(item, dry_run=dry_run) for item in opportunities]
        if self.publisher is not None:
            for message in messages:
                self.publisher(message)
        return messages

    def format_opportunity(self, opportunity: FundingOpportunity, *, dry_run: bool = False) -> str:
        prefix = "DRY-RUN " if dry_run else ""
        return (
            f"{prefix}{opportunity.exchange} {opportunity.symbol} "
            f"net={opportunity.net_rate} annualized={opportunity.annualized_net_rate} "
            f"spread_bps={opportunity.spread_bps} liquidity_usd={opportunity.liquidity_usd}"
        )

    def _to_ticker(self, payload: dict[str, Any]) -> Ticker:
        return Ticker(
            exchange=str(payload["exchange"]),
            symbol=str(payload["symbol"]),
            market_type=MarketType(str(payload["market_type"])),
            bid=Decimal(str(payload["bid"])),
            ask=Decimal(str(payload["ask"])),
            last=Decimal(str(payload["last"])),
            ts=datetime.fromisoformat(str(payload["ts"])),
        )

    def _to_funding(self, payload: dict[str, Any]) -> FundingRate:
        predicted = payload.get("predicted_rate")
        return FundingRate(
            exchange=str(payload["exchange"]),
            symbol=str(payload["symbol"]),
            rate=Decimal(str(payload["rate"])),
            predicted_rate=(Decimal(str(predicted)) if predicted is not None else None),
            next_funding_time=datetime.fromisoformat(str(payload["next_funding_time"])),
            ts=datetime.fromisoformat(str(payload["ts"])),
        )
