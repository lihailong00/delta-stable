"""Funding arbitrage service orchestration."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from arb.execution.executor import ExecutionResult
from arb.execution.router import RouteDecision
from arb.market.schemas import MarketSnapshot, coerce_market_snapshot
from arb.models import MarketType, Position, PositionDirection
from arb.risk.position_monitor import PositionMonitor
from arb.runtime.exchange_manager import LiveExchangeManager, ScanTarget
from arb.runtime.pipeline import OpportunityPipeline
from arb.runtime.realtime_scanner import RealtimeScanner
from arb.runtime.schemas import ActiveFundingArb
from arb.scanner.funding_scanner import FundingOpportunity
from arb.strategy.engine import StrategyAction, StrategyState
from arb.strategy.spot_perp import SpotPerpInputs, SpotPerpStrategy
from arb.workflows.close_position import ClosePositionRequest, ClosePositionResult, ClosePositionWorkflow
from arb.workflows.open_position import OpenPositionRequest, OpenPositionResult, OpenPositionWorkflow, VenueClients


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


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
        position_monitor: PositionMonitor | None = None,
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
        self.position_monitor = position_monitor or PositionMonitor()
        self.position_quantity = position_quantity
        self.strategy_name = strategy_name
        self.active_positions: dict[str, ActiveFundingArb] = {}

    async def run_once(
        self,
        targets: list[ScanTarget],
        *,
        dry_run: bool = False,
        now: datetime | None = None,
    ) -> dict[str, object]:
        current_time = now or _utc_now()
        scan_result = await self.scanner.scan_once(targets, dry_run=dry_run)
        snapshots = [coerce_market_snapshot(snapshot) for snapshot in scan_result["snapshots"]]
        opportunities = scan_result["opportunities"]
        snapshot_index = self._snapshot_index(snapshots)

        closed: list[ClosePositionResult] = []
        for key, position in list(self.active_positions.items()):
            snapshot = snapshot_index.get((position.exchange, position.symbol))
            if snapshot is None:
                continue
            monitor_decision = self.position_monitor.evaluate(
                symbol=position.symbol,
                snapshot=snapshot,
                spot_quantity=position.spot_quantity,
                perp_quantity=position.perp_quantity,
                opened_at=position.opened_at,
                max_holding_period=self.strategy.max_holding_period,
                min_expected_rate=self.strategy.close_funding_rate,
                liquidation_price=position.liquidation_price,
                now=current_time,
            )
            if monitor_decision.should_close:
                result = await self._close_position(position, snapshot, reason=monitor_decision.close_reason or "risk_close")
                closed.append(result)
                if result.status in {"closed", "reduced"}:
                    del self.active_positions[key]
                    self.manager.release_slot(key)
                continue
            decision = self.strategy.evaluate(
                SpotPerpInputs(
                    symbol=position.symbol,
                    funding_rate=snapshot.funding.rate if snapshot.funding is not None else Decimal("0"),
                    spot_price=snapshot.ticker.ask,
                    perp_price=snapshot.ticker.bid,
                    spot_quantity=position.spot_quantity,
                    perp_quantity=position.perp_quantity,
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
                spot_quantity = self.position_quantity
                perp_quantity = self.position_quantity
                if result.execution is not None and len(result.execution.orders) == 2:
                    spot_quantity = Decimal(str(result.execution.orders[0].filled_quantity or self.position_quantity))
                    perp_quantity = Decimal(str(result.execution.orders[1].filled_quantity or self.position_quantity))
                self.active_positions[key] = ActiveFundingArb(
                    workflow_id=key,
                    exchange=opportunity.exchange,
                    symbol=opportunity.symbol,
                    quantity=self.position_quantity,
                    spot_quantity=spot_quantity,
                    perp_quantity=perp_quantity,
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
        snapshot: MarketSnapshot,
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
                spot_price=snapshot.ticker.ask,
                perp_price=snapshot.ticker.bid,
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
        if result.execution is not None and result.status == "opened":
            self._persist_execution(result.execution)
            self._persist_position_pair(
                exchange=opportunity.exchange,
                symbol=opportunity.symbol,
                quantity=self.position_quantity,
                spot_entry=snapshot.ticker.ask,
                perp_entry=snapshot.ticker.bid,
                closed=False,
            )
        return result

    async def _close_position(
        self,
        position: ActiveFundingArb,
        snapshot: MarketSnapshot,
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
                spot_quantity=position.spot_quantity,
                perp_quantity=position.perp_quantity,
                spot_price=snapshot.ticker.bid,
                perp_price=snapshot.ticker.ask,
                venue_clients={position.exchange: self.venues[position.exchange]},
                preferred_exchange=position.exchange,
                funding_rate=snapshot.funding.rate if snapshot.funding is not None else Decimal("0"),
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
        if result.execution is not None and result.status in {"closed", "reduced"}:
            self._persist_execution(result.execution)
            self._persist_position_pair(
                exchange=position.exchange,
                symbol=position.symbol,
                quantity=max(position.spot_quantity, position.perp_quantity),
                spot_entry=snapshot.ticker.bid,
                perp_entry=snapshot.ticker.ask,
                closed=True,
            )
        return result

    def _key(self, exchange: str, symbol: str) -> str:
        return f"{self.strategy_name}:{exchange}:{symbol}"

    def _snapshot_index(self, snapshots: list[MarketSnapshot]) -> dict[tuple[str, str], MarketSnapshot]:
        indexed: dict[tuple[str, str], MarketSnapshot] = {}
        for snapshot in snapshots:
            funding = snapshot.funding
            if funding is None:
                continue
            indexed[(funding.exchange, funding.symbol)] = snapshot
        return indexed

    def _persist_execution(self, execution: ExecutionResult) -> None:
        for order in execution.orders:
            self.pipeline.record_order(order)
        for order in execution.adjustments:
            self.pipeline.record_order(order)
        for fill in execution.fills:
            self.pipeline.record_fill(fill)

    def _persist_position_pair(
        self,
        *,
        exchange: str,
        symbol: str,
        quantity: Decimal,
        spot_entry: Decimal,
        perp_entry: Decimal,
        closed: bool,
    ) -> None:
        active_quantity = Decimal("0") if closed else quantity
        self.pipeline.record_position(
            Position(
                exchange=exchange,
                symbol=symbol,
                market_type=MarketType.SPOT,
                direction=PositionDirection.LONG,
                quantity=active_quantity,
                entry_price=spot_entry,
                mark_price=spot_entry,
            )
        )
        self.pipeline.record_position(
            Position(
                exchange=exchange,
                symbol=symbol,
                market_type=MarketType.PERPETUAL,
                direction=PositionDirection.SHORT,
                quantity=active_quantity,
                entry_price=perp_entry,
                mark_price=perp_entry,
            )
        )
