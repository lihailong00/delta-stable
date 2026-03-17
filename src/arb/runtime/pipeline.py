"""Persistence and output pipeline for realtime scans."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Protocol

from arb.market.schemas import MarketSnapshot, coerce_market_snapshot
from arb.models import Fill, FundingRate, MarketType, Order, Position, Ticker
from arb.monitoring.metrics import MetricsRegistry
from arb.scanner.funding_scanner import FundingOpportunity
from arb.storage.repository import Repository


class MessagePublisher(Protocol):
    def __call__(self, message: str) -> None: ...


class OpportunityPipeline:
    """Persist normalized snapshots and publish scan output."""

    def __init__(
        self,
        *,
        repository: Repository | None = None,
        metrics: MetricsRegistry | None = None,
        publisher: MessagePublisher | None = None,
    ) -> None:
        self.repository = repository
        self.metrics = metrics or MetricsRegistry()
        self.publisher = publisher

    def process(
        self,
        snapshots: list[MarketSnapshot | dict[str, object]],
        opportunities: list[FundingOpportunity],
        *,
        dry_run: bool = False,
    ) -> list[str]:
        self.persist_snapshots(snapshots)
        messages = self.publish_opportunities(opportunities, dry_run=dry_run)
        self.metrics.set_gauge("realtime.opportunity_count", Decimal(len(opportunities)))
        return messages

    def persist_snapshots(self, snapshots: list[MarketSnapshot | dict[str, object]]) -> None:
        for raw_snapshot in snapshots:
            snapshot = (
                raw_snapshot
                if isinstance(raw_snapshot, MarketSnapshot)
                else coerce_market_snapshot(raw_snapshot)
            )
            self.metrics.increment("realtime.snapshots")
            ticker = snapshot.ticker
            if ticker and self.repository is not None:
                self.repository.save_ticker(ticker)
            funding = snapshot.funding
            if funding and self.repository is not None:
                self.repository.save_funding(funding)

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

    def record_workflow_state(
        self,
        *,
        workflow_id: str,
        workflow_type: str,
        exchange: str,
        symbol: str,
        status: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        self.metrics.increment(f"workflow.{status}")
        if self.repository is not None:
            self.repository.save_workflow_state(
                workflow_id=workflow_id,
                workflow_type=workflow_type,
                exchange=exchange,
                symbol=symbol,
                status=status,
                payload=payload,
            )

    def record_order(self, order: Order) -> None:
        if self.repository is not None:
            self.repository.save_order(order)

    def record_fill(self, fill: Fill) -> None:
        if self.repository is not None:
            self.repository.save_fill(fill)

    def record_position(self, position: Position) -> None:
        if self.repository is not None:
            self.repository.save_position(position)

    def format_opportunity(self, opportunity: FundingOpportunity, *, dry_run: bool = False) -> str:
        prefix = "DRY-RUN " if dry_run else ""
        return (
            f"{prefix}{opportunity.exchange} {opportunity.symbol} "
            f"net={opportunity.net_rate} annualized={opportunity.annualized_net_rate} "
            f"spread_bps={opportunity.spread_bps} liquidity_usd={opportunity.liquidity_usd}"
        )
