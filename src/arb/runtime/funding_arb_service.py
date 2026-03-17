"""Funding arbitrage service orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from arb.execution.router import RouteDecision
from arb.runtime.exchange_manager import LiveExchangeManager, ScanTarget
from arb.runtime.pipeline import OpportunityPipeline
from arb.runtime.realtime_scanner import RealtimeScanner
from arb.scanner.funding_scanner import FundingOpportunity
from arb.strategy.engine import StrategyAction, StrategyState
from arb.strategy.spot_perp import SpotPerpInputs, SpotPerpStrategy
from arb.workflows.close_position import ClosePositionRequest, ClosePositionResult, ClosePositionWorkflow
from arb.workflows.open_position import OpenPositionRequest, OpenPositionResult, OpenPositionWorkflow, VenueClients


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass(slots=True)
class ActiveFundingArb:
    workflow_id: str
    exchange: str
    symbol: str
    quantity: Decimal
    opened_at: datetime
    route: RouteDecision | None = None
    state: StrategyState = field(default_factory=StrategyState)


class FundingArbService:
    """Drive scan, open, monitor and close loops for funding arbitrage."""

    def __init__(
        self,
        *,
        scanner: RealtimeScanner,
        open_workflow: OpenPositionWorkflow,
        close_workflow: ClosePositionWorkflow,
        venues: dict[str, VenueClients],
        manager: LiveExchangeManager,
        pipeline: OpportunityPipeline,
        strategy: SpotPerpStrategy | None = None,
        position_quantity: Decimal = Decimal("1"),
        strategy_name: str = "funding_spot_perp",
    ) -> None:
        self.scanner = scanner
        self.open_workflow = open_workflow
        self.close_workflow = close_workflow
        self.venues = venues
        self.manager = manager
        self.pipeline = pipeline
        self.strategy = strategy or SpotPerpStrategy()
        self.position_quantity = position_quantity
        self.strategy_name = strategy_name
        self.active_positions: dict[str, ActiveFundingArb] = {}

    async def run_once(
        self,
        targets: list[ScanTarget],
        *,
        dry_run: bool = False,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current_time = now or _utc_now()
        scan_result = await self.scanner.scan_once(targets, dry_run=dry_run)
        snapshots = scan_result["snapshots"]
        opportunities = scan_result["opportunities"]
        snapshot_index = self._snapshot_index(snapshots)

        closed: list[ClosePositionResult] = []
        for key, position in list(self.active_positions.items()):
            snapshot = snapshot_index.get((position.exchange, position.symbol))
            if snapshot is None:
                continue
            decision = self.strategy.evaluate(
                SpotPerpInputs(
                    symbol=position.symbol,
                    funding_rate=Decimal(str(snapshot["funding"]["rate"])),
                    spot_price=Decimal(str(snapshot["ticker"]["ask"])),
                    perp_price=Decimal(str(snapshot["ticker"]["bid"])),
                    spot_quantity=position.quantity,
                    perp_quantity=position.quantity,
                ),
                state=position.state,
                now=current_time,
            )
            if decision.action is not StrategyAction.CLOSE:
                continue
            result = await self._close_position(position, snapshot, reason=decision.reason)
            closed.append(result)
            if result.status in {"closed", "reduced"}:
                del self.active_positions[key]
                self.manager.release_slot(key)

        selected = self.scanner.select_opportunities(
            opportunities,
            active_keys={f"{position.exchange}:{position.symbol}" for position in self.active_positions.values()},
        )
        opened: list[OpenPositionResult] = []
        for opportunity in selected:
            key = self._key(opportunity.exchange, opportunity.symbol)
            if key in self.active_positions:
                continue
            if not self.manager.acquire_slot(key):
                continue
            snapshot = snapshot_index.get((opportunity.exchange, opportunity.symbol))
            if snapshot is None or opportunity.exchange not in self.venues:
                self.manager.release_slot(key)
                continue
            result = await self._open_position(opportunity, snapshot, current_time)
            opened.append(result)
            if result.status == "opened":
                self.active_positions[key] = ActiveFundingArb(
                    workflow_id=key,
                    exchange=opportunity.exchange,
                    symbol=opportunity.symbol,
                    quantity=self.position_quantity,
                    opened_at=current_time,
                    route=result.route,
                    state=StrategyState(is_open=True, opened_at=current_time, hedge_ratio=Decimal("1")),
                )
            else:
                self.manager.release_slot(key)

        return {
            "scan": scan_result,
            "opened": opened,
            "closed": closed,
            "active": list(self.active_positions.values()),
        }

    async def _open_position(
        self,
        opportunity: FundingOpportunity,
        snapshot: dict[str, Any],
        now: datetime,
    ) -> OpenPositionResult:
        workflow_id = self._key(opportunity.exchange, opportunity.symbol)
        self.pipeline.record_workflow_state(
            workflow_id=workflow_id,
            workflow_type=self.strategy_name,
            exchange=opportunity.exchange,
            symbol=opportunity.symbol,
            status="opening",
            payload={"net_rate": str(opportunity.net_rate)},
        )
        result = await self.open_workflow.execute(
            OpenPositionRequest(
                symbol=opportunity.symbol,
                quantity=self.position_quantity,
                funding_rate=opportunity.gross_rate,
                spot_price=Decimal(str(snapshot["ticker"]["ask"])),
                perp_price=Decimal(str(snapshot["ticker"]["bid"])),
                venue_clients={opportunity.exchange: self.venues[opportunity.exchange]},
                preferred_exchange=opportunity.exchange,
                maker_fee_rate=Decimal("0"),
                taker_fee_rate=Decimal("0"),
                spread_bps=opportunity.spread_bps,
                max_slippage_bps=Decimal("10"),
            )
        )
        self.pipeline.record_workflow_state(
            workflow_id=workflow_id,
            workflow_type=self.strategy_name,
            exchange=opportunity.exchange,
            symbol=opportunity.symbol,
            status="open" if result.status == "opened" else result.status,
            payload={"reason": result.reason, "attempts": result.attempts, "opened_at": now.isoformat()},
        )
        return result

    async def _close_position(
        self,
        position: ActiveFundingArb,
        snapshot: dict[str, Any],
        *,
        reason: str,
    ) -> ClosePositionResult:
        self.pipeline.record_workflow_state(
            workflow_id=position.workflow_id,
            workflow_type=self.strategy_name,
            exchange=position.exchange,
            symbol=position.symbol,
            status="closing",
            payload={"reason": reason},
        )
        result = await self.close_workflow.execute(
            ClosePositionRequest(
                symbol=position.symbol,
                spot_quantity=position.quantity,
                perp_quantity=position.quantity,
                spot_price=Decimal(str(snapshot["ticker"]["bid"])),
                perp_price=Decimal(str(snapshot["ticker"]["ask"])),
                venue_clients={position.exchange: self.venues[position.exchange]},
                preferred_exchange=position.exchange,
                funding_rate=Decimal(str(snapshot["funding"]["rate"])),
                min_expected_rate=self.strategy.close_funding_rate,
                opened_at=position.opened_at,
                max_holding_period=self.strategy.max_holding_period,
                close_reason=reason,
                maker_fee_rate=Decimal("0"),
                taker_fee_rate=Decimal("0"),
                spread_bps=Decimal("1"),
                max_slippage_bps=Decimal("10"),
            )
        )
        self.pipeline.record_workflow_state(
            workflow_id=position.workflow_id,
            workflow_type=self.strategy_name,
            exchange=position.exchange,
            symbol=position.symbol,
            status="closed" if result.status in {"closed", "reduced"} else result.status,
            payload={"reason": result.reason, "retries": result.retries},
        )
        return result

    def _key(self, exchange: str, symbol: str) -> str:
        return f"{self.strategy_name}:{exchange}:{symbol}"

    def _snapshot_index(self, snapshots: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
        indexed: dict[tuple[str, str], dict[str, Any]] = {}
        for snapshot in snapshots:
            funding = snapshot.get("funding")
            if funding is None:
                continue
            indexed[(str(funding["exchange"]), str(funding["symbol"]))] = snapshot
        return indexed
