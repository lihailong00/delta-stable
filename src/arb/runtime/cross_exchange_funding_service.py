"""Cross-exchange perpetual funding arbitrage service."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from arb.execution.executor import ExecutionResult
from arb.market.schemas import MarketSnapshot, coerce_market_snapshot
from arb.models import MarketType, Position, PositionDirection
from arb.runtime.enums import WorkflowStatus
from arb.runtime.exchange_manager import LiveExchangeManager, ScanTarget
from arb.runtime.pipeline import OpportunityPipeline
from arb.runtime.schemas import ActiveCrossExchangeArb, CrossExchangeOpportunity, CrossExchangeRunResult
from arb.strategy.engine import StrategyAction, StrategyState
from arb.strategy.perp_spread import PerpSpreadInputs, PerpSpreadStrategy
from arb.workflows.enums import ClosePositionStatus, OpenPositionStatus
from arb.workflows.close_position import CrossExchangeCloseRequest, ClosePositionResult, ClosePositionWorkflow
from arb.workflows.open_position import CrossExchangeOpenRequest, OpenPositionResult, OpenPositionWorkflow, VenueClientBundle


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


class CrossExchangeFundingService:
    """Drive cross-exchange perpetual funding spread opportunities."""

    def __init__(
        self,
        *,
        manager: LiveExchangeManager,
        pipeline: OpportunityPipeline,
        open_workflow: OpenPositionWorkflow,
        close_workflow: ClosePositionWorkflow,
        venues: dict[str, VenueClientBundle],
        strategy: PerpSpreadStrategy | None = None,
        position_quantity: Decimal = Decimal("1"),
        strategy_name: str = "cross_exchange_perp_spread",
    ) -> None:
        self.manager = manager
        self.pipeline = pipeline
        self.open_workflow = open_workflow
        self.close_workflow = close_workflow
        self.venues = venues
        self.strategy = strategy or PerpSpreadStrategy()
        self.position_quantity = position_quantity
        self.strategy_name = strategy_name
        self.active_positions: dict[str, ActiveCrossExchangeArb] = {}

    async def run_once(
        self,
        targets: list[ScanTarget],
        *,
        now: datetime | None = None,
    ) -> CrossExchangeRunResult:
        current_time = now or _utc_now()
        snapshots = [coerce_market_snapshot(snapshot) for snapshot in await self.manager.collect_snapshots(targets)]
        snapshot_index = self._snapshot_index(snapshots)

        closed: list[ClosePositionResult] = []
        for key, position in list(self.active_positions.items()):
            long_snapshot = snapshot_index.get((position.long_exchange, position.symbol))
            short_snapshot = snapshot_index.get((position.short_exchange, position.symbol))
            if long_snapshot is None or short_snapshot is None:
                continue
            decision = self.strategy.evaluate(
                PerpSpreadInputs(
                    symbol=position.symbol,
                    long_exchange=position.long_exchange,
                    short_exchange=position.short_exchange,
                    long_funding_rate=long_snapshot.funding.rate if long_snapshot.funding is not None else Decimal("0"),
                    short_funding_rate=short_snapshot.funding.rate if short_snapshot.funding is not None else Decimal("0"),
                    long_price=long_snapshot.ticker.ask,
                    short_price=short_snapshot.ticker.bid,
                    long_quantity=position.long_quantity,
                    short_quantity=position.short_quantity,
                ),
                state=position.state,
            )
            if decision.action is not StrategyAction.CLOSE:
                continue
            close_result = await self._close_position(
                position,
                long_snapshot,
                short_snapshot,
                reason=decision.reason,
            )
            closed.append(close_result)
            if close_result.status == ClosePositionStatus.CLOSED:
                del self.active_positions[key]
                self.manager.release_slot(key)

        opportunities = self._opportunities(snapshots)
        opened: list[OpenPositionResult] = []
        for opportunity in opportunities:
            workflow_id = self._workflow_id(opportunity.long_exchange, opportunity.short_exchange, opportunity.symbol)
            if workflow_id in self.active_positions:
                continue
            if not self.manager.acquire_slot(workflow_id):
                continue
            open_result = await self._open_position(opportunity, current_time)
            opened.append(open_result)
            if open_result.status == OpenPositionStatus.OPENED:
                self.active_positions[workflow_id] = ActiveCrossExchangeArb(
                    workflow_id=workflow_id,
                    symbol=opportunity.symbol,
                    long_exchange=opportunity.long_exchange,
                    short_exchange=opportunity.short_exchange,
                    quantity=self.position_quantity,
                    long_quantity=self._filled_quantity(open_result, 0),
                    short_quantity=self._filled_quantity(open_result, 1),
                    opened_at=current_time,
                    state=StrategyState(is_open=True, opened_at=current_time, hedge_ratio=Decimal("1")),
                )
            else:
                self.manager.release_slot(workflow_id)

        return CrossExchangeRunResult(
            snapshots=snapshots,
            opportunities=opportunities,
            opened=opened,
            closed=closed,
            active=list(self.active_positions.values()),
        )

    async def _open_position(
        self,
        opportunity: CrossExchangeOpportunity,
        now: datetime,
    ) -> OpenPositionResult:
        workflow_id = self._workflow_id(opportunity.long_exchange, opportunity.short_exchange, opportunity.symbol)
        self.pipeline.record_workflow_state(
            workflow_id=workflow_id,
            workflow_type=self.strategy_name,
            exchange=opportunity.short_exchange,
            symbol=opportunity.symbol,
            status=WorkflowStatus.OPENING,
            payload={
                "long_exchange": opportunity.long_exchange,
                "short_exchange": opportunity.short_exchange,
                "spread_rate": str(opportunity.spread_rate),
            },
        )
        result = await self.open_workflow.execute_cross_exchange(
            CrossExchangeOpenRequest(
                symbol=opportunity.symbol,
                quantity=self.position_quantity,
                long_exchange=opportunity.long_exchange,
                short_exchange=opportunity.short_exchange,
                long_price=opportunity.long_price,
                short_price=opportunity.short_price,
                venue_clients=self.venues,
                spread_bps=Decimal("1"),
                max_slippage_bps=Decimal("10"),
            )
        )
        self.pipeline.record_workflow_state(
            workflow_id=workflow_id,
            workflow_type=self.strategy_name,
            exchange=opportunity.short_exchange,
            symbol=opportunity.symbol,
            status=WorkflowStatus.OPEN if result.status == OpenPositionStatus.OPENED else result.status,
            payload={"opened_at": now.isoformat(), "reason": result.reason},
        )
        if result.execution is not None and result.status == OpenPositionStatus.OPENED:
            self._persist_execution(result.execution)
            self._persist_positions(
                opportunity=opportunity,
                long_price=opportunity.long_price,
                short_price=opportunity.short_price,
                closed=False,
            )
        return result

    async def _close_position(
        self,
        position: ActiveCrossExchangeArb,
        long_snapshot: MarketSnapshot,
        short_snapshot: MarketSnapshot,
        *,
        reason: str,
    ) -> ClosePositionResult:
        self.pipeline.record_workflow_state(
            workflow_id=position.workflow_id,
            workflow_type=self.strategy_name,
            exchange=position.short_exchange,
            symbol=position.symbol,
            status=WorkflowStatus.CLOSING,
            payload={"reason": reason},
        )
        result = await self.close_workflow.execute_cross_exchange(
            CrossExchangeCloseRequest(
                symbol=position.symbol,
                long_exchange=position.long_exchange,
                short_exchange=position.short_exchange,
                long_quantity=position.long_quantity,
                short_quantity=position.short_quantity,
                long_price=long_snapshot.ticker.bid,
                short_price=short_snapshot.ticker.ask,
                venue_clients=self.venues,
                close_reason=reason,
                max_slippage_bps=Decimal("10"),
            )
        )
        self.pipeline.record_workflow_state(
            workflow_id=position.workflow_id,
            workflow_type=self.strategy_name,
            exchange=position.short_exchange,
            symbol=position.symbol,
            status=WorkflowStatus.CLOSED if result.status == ClosePositionStatus.CLOSED else result.status,
            payload={"reason": result.reason},
        )
        if result.execution is not None and result.status == ClosePositionStatus.CLOSED:
            self._persist_execution(result.execution)
            self._persist_positions(
                opportunity=CrossExchangeOpportunity(
                    symbol=position.symbol,
                    long_exchange=position.long_exchange,
                    short_exchange=position.short_exchange,
                    spread_rate=Decimal("0"),
                    long_price=long_snapshot.ticker.bid,
                    short_price=short_snapshot.ticker.ask,
                ),
                long_price=long_snapshot.ticker.bid,
                short_price=short_snapshot.ticker.ask,
                closed=True,
            )
        return result

    def _opportunities(self, snapshots: list[MarketSnapshot]) -> list[CrossExchangeOpportunity]:
        by_symbol: dict[str, list[MarketSnapshot]] = {}
        for snapshot in snapshots:
            funding = snapshot.funding
            if funding is None:
                continue
            by_symbol.setdefault(funding.symbol, []).append(snapshot)

        opportunities: list[CrossExchangeOpportunity] = []
        for symbol, items in by_symbol.items():
            for long_snapshot in items:
                for short_snapshot in items:
                    long_funding = long_snapshot.funding
                    short_funding = short_snapshot.funding
                    if long_funding is None or short_funding is None:
                        continue
                    long_exchange = long_funding.exchange
                    short_exchange = short_funding.exchange
                    if long_exchange == short_exchange:
                        continue
                    inputs = PerpSpreadInputs(
                        symbol=symbol,
                        long_exchange=long_exchange,
                        short_exchange=short_exchange,
                        long_funding_rate=long_funding.rate,
                        short_funding_rate=short_funding.rate,
                        long_price=long_snapshot.ticker.ask,
                        short_price=short_snapshot.ticker.bid,
                    )
                    decision = self.strategy.evaluate(inputs)
                    if decision.action is not StrategyAction.OPEN:
                        continue
                    opportunities.append(
                        CrossExchangeOpportunity(
                            symbol=symbol,
                            long_exchange=long_exchange,
                            short_exchange=short_exchange,
                            spread_rate=self.strategy.spread_rate(inputs),
                            long_price=inputs.long_price,
                            short_price=inputs.short_price,
                        )
                    )
        opportunities.sort(key=lambda item: item.spread_rate, reverse=True)
        return opportunities

    def _snapshot_index(self, snapshots: list[MarketSnapshot]) -> dict[tuple[str, str], MarketSnapshot]:
        indexed: dict[tuple[str, str], MarketSnapshot] = {}
        for snapshot in snapshots:
            funding = snapshot.funding
            if funding is None:
                continue
            indexed[(funding.exchange, funding.symbol)] = snapshot
        return indexed

    def _workflow_id(self, long_exchange: str, short_exchange: str, symbol: str) -> str:
        return f"{self.strategy_name}:{long_exchange}:{short_exchange}:{symbol}"

    def _filled_quantity(self, result: OpenPositionResult, index: int) -> Decimal:
        if result.execution is None or len(result.execution.orders) <= index:
            return self.position_quantity
        return Decimal(str(result.execution.orders[index].filled_quantity or self.position_quantity))

    def _persist_execution(self, execution: ExecutionResult) -> None:
        for order in execution.orders:
            self.pipeline.record_order(order)
        for order in execution.adjustments:
            self.pipeline.record_order(order)
        for fill in execution.fills:
            self.pipeline.record_fill(fill)

    def _persist_positions(
        self,
        *,
        opportunity: CrossExchangeOpportunity,
        long_price: Decimal,
        short_price: Decimal,
        closed: bool,
    ) -> None:
        quantity = Decimal("0") if closed else self.position_quantity
        self.pipeline.record_position(
            Position(
                exchange=opportunity.long_exchange,
                symbol=opportunity.symbol,
                market_type=MarketType.PERPETUAL,
                direction=PositionDirection.LONG,
                quantity=quantity,
                entry_price=long_price,
                mark_price=long_price,
            )
        )
        self.pipeline.record_position(
            Position(
                exchange=opportunity.short_exchange,
                symbol=opportunity.symbol,
                market_type=MarketType.PERPETUAL,
                direction=PositionDirection.SHORT,
                quantity=quantity,
                entry_price=short_price,
                mark_price=short_price,
            )
        )
