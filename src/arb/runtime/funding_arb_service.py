"""Funding arbitrage service orchestration."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from arb.execution.executor import ExecutionResult
from arb.execution.router import RouteDecision

from arb.market.schemas import MarketSnapshot, coerce_market_snapshot
from arb.models import MarketType, Position, PositionDirection
from arb.risk.checks import RiskAlert
from arb.risk.position_monitor import PositionMonitor, PositionMonitorDecision
from arb.runtime.enums import WorkflowStatus
from arb.runtime.exchange_manager import LiveExchangeManager, ScanTarget
from arb.runtime.pipeline import OpportunityPipeline
from arb.runtime.realtime_scanner import RealtimeScanner
from arb.runtime.schemas import ActiveFundingArb, FundingArbRunResult, RealtimeScanResult
from arb.scanner.funding_scanner import FundingOpportunity
from arb.schemas.base import SerializableValue
from arb.strategy.engine import StrategyAction, StrategyState
from arb.strategy.spot_perp import SpotPerpInputs, SpotPerpStrategy
from arb.workflows.close_position import ClosePositionRequest, ClosePositionResult, ClosePositionWorkflow
from arb.workflows.enums import ClosePositionStatus, OpenPositionStatus
from arb.workflows.open_position import OpenPositionRequest, OpenPositionResult, OpenPositionWorkflow, VenueClientBundle


def _utc_now() -> datetime:
    """返回当前 UTC 时间，保证服务内部的时间基准一致。"""

    return datetime.now(tz=timezone.utc)


@dataclass(slots=True, frozen=True)
class MonitorStateSignature:
    """监控状态缓存签名。

    用于判断某个 workflow 的监控状态是否真的发生变化，
    从而避免在 `run_once()` 的每一轮里重复写相同的 workflow 状态。
    """

    status: WorkflowStatus
    alert_reasons: tuple[str, ...] = ()


class FundingArbService:
    """资金费率套利服务的总编排入口。

    这个服务本身不直接负责行情抓取、策略判断、下单执行或风控细节，
    而是把这些组件串起来，完成一次完整的“扫描 -> 开仓 -> 持仓监控 -> 平仓”循环。
    """

    def __init__(
        self,
        *,
        scanner: RealtimeScanner,
        open_workflow: OpenPositionWorkflow,
        close_workflow: ClosePositionWorkflow,
        venues: dict[str, VenueClientBundle],
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
        # 当前由服务维护的活跃资金费率套利头寸，key 采用【策略名+交易所+标的】拼接。
        self.active_positions: dict[str, ActiveFundingArb] = {}
        # 缓存最近一次已写入的监控状态，避免每轮都重复写相同的 workflow 状态。
        self._monitor_state_signatures: dict[str, MonitorStateSignature] = {}

    async def run_once(
        self,
        targets: list[ScanTarget],
        *,
        dry_run: bool = False,
        now: datetime | None = None,
    ) -> FundingArbRunResult:
        """执行一次完整的资金费率套利循环。

        执行顺序分成两大阶段：
        1. 先扫描市场，并对当前已持有的仓位做风控检查和策略平仓判断
        2. 再从新的候选机会里挑选可开仓标的，尝试发起开仓

        返回值会同时带回本轮扫描结果、成功/失败的开平仓结果，以及最新的活跃仓位快照。
        """

        current_time = now or _utc_now()
        # 先做一次实时扫描，拿到本轮快照和候选机会。
        raw_scan_result = await self.scanner.scan_once(targets, dry_run=dry_run)
        # 扫描器可能返回强类型对象，也可能返回字典，这里统一归一化。
        scan_result = self._coerce_scan_result(raw_scan_result)
        snapshots = scan_result.snapshots
        opportunities = scan_result.opportunities
        # 以 (exchange, symbol) 建索引，后续查找某个持仓/机会的对应行情时更高效。
        snapshot_index = self._snapshot_index(snapshots)

        closed: list[ClosePositionResult] = []
        # 第一阶段：遍历当前活跃持仓，优先做风险检查和策略平仓判断。
        for key, position in list(self.active_positions.items()):
            snapshot = snapshot_index.get((position.exchange, position.symbol))
            # 没有拿到对应快照时，本轮无法安全评估，直接跳过，等待下一轮。
            if snapshot is None:
                continue
            # 风控层优先于策略层；一旦触发风险条件，应直接走平仓流程。
            monitor_decision = self.position_monitor.evaluate(
                symbol=position.symbol,
                snapshot=snapshot,
                spot_quantity=position.spot_quantity,
                perp_quantity=position.perp_quantity,
                opened_at=position.opened_at,
                max_holding_period=self.strategy.max_holding_period,
                min_expected_rate=self.strategy.close_funding_rate,
                funding_interval_hours=(
                    snapshot.funding.funding_interval_hours
                    if snapshot.funding is not None
                    else self.strategy.threshold_interval_hours
                ),
                comparison_interval_hours=self.strategy.threshold_interval_hours,
                liquidation_price=position.liquidation_price,
                now=current_time,
            )
            if monitor_decision.should_close:
                # 风控触发时，使用风控给出的理由记录这次平仓动作。
                close_result = await self._close_position(
                    position,
                    snapshot,
                    reason=monitor_decision.close_reason or "risk_close",
                    alerts=monitor_decision.alerts,
                )
                closed.append(close_result)
                # 完全平仓后才释放槽位并移出活跃集合；部分减仓则继续保留在监控列表里。
                if close_result.status == ClosePositionStatus.CLOSED:
                    del self.active_positions[key]
                    self.manager.release_slot(key)
                    self._monitor_state_signatures.pop(position.workflow_id, None)
                elif close_result.status == ClosePositionStatus.REDUCED:
                    self.active_positions[key] = position.model_copy(
                        update={
                            "spot_quantity": close_result.remaining_spot_quantity,
                            "perp_quantity": close_result.remaining_perp_quantity,
                        }
                    )
                    self._monitor_state_signatures.pop(position.workflow_id, None)
                continue
            self._record_monitor_state(position, monitor_decision)
            # 没有触发风控时，再交给策略判断当前持仓是否需要退出。
            decision = self.strategy.evaluate(
                SpotPerpInputs(
                    symbol=position.symbol,
                    funding_rate=snapshot.funding.rate if snapshot.funding is not None else Decimal("0"),
                    funding_interval_hours=(
                        snapshot.funding.funding_interval_hours
                        if snapshot.funding is not None
                        else self.strategy.threshold_interval_hours
                    ),
                    spot_price=snapshot.ticker.ask,
                    perp_price=snapshot.ticker.bid,
                    spot_quantity=position.spot_quantity,
                    perp_quantity=position.perp_quantity,
                ),
                state=position.state,
                now=current_time,
            )
            # 当前服务只在持仓阶段消费 CLOSE 动作；其他动作保持现状即可。
            if decision.action is not StrategyAction.CLOSE:
                continue
            close_result = await self._close_position(position, snapshot, reason=decision.reason)
            closed.append(close_result)
            if close_result.status == ClosePositionStatus.CLOSED:
                del self.active_positions[key]
                self.manager.release_slot(key)
                self._monitor_state_signatures.pop(position.workflow_id, None)
            elif close_result.status == ClosePositionStatus.REDUCED:
                self.active_positions[key] = position.model_copy(
                    update={
                        "spot_quantity": close_result.remaining_spot_quantity,
                        "perp_quantity": close_result.remaining_perp_quantity,
                    }
                )
                self._monitor_state_signatures.pop(position.workflow_id, None)

        # 第二阶段：从扫描机会中选出本轮允许尝试的新机会。
        selected = self.scanner.select_opportunities(
            opportunities,
            # 已持仓标的不再重复参与开仓筛选，避免同一标的重复占仓。
            active_keys={f"{position.exchange}:{position.symbol}" for position in self.active_positions.values()},
        )
        opened: list[OpenPositionResult] = []
        for opportunity in selected:
            key = self._key(opportunity.exchange, opportunity.symbol)
            # 双重保护：即使上游筛选过，这里也不允许重复写入同一活跃头寸。
            if key in self.active_positions:
                continue
            # 通过 manager 控制并发/容量，拿不到槽位时直接放弃本次开仓。
            if not self.manager.acquire_slot(key):
                continue
            snapshot = snapshot_index.get((opportunity.exchange, opportunity.symbol))
            # 缺行情或缺 venue client 时无法执行交易，需要释放槽位。
            if snapshot is None or opportunity.exchange not in self.venues:
                self.manager.release_slot(key)
                continue
            open_result = await self._open_position(opportunity, snapshot, current_time)
            opened.append(open_result)
            if open_result.status == OpenPositionStatus.OPENED:
                # 默认使用配置的目标下单数量；若执行结果里带有真实成交量，则以真实成交量为准。
                spot_quantity = self.position_quantity
                perp_quantity = self.position_quantity
                if open_result.execution is not None and len(open_result.execution.orders) == 2:
                    spot_quantity = Decimal(
                        str(open_result.execution.orders[0].filled_quantity or self.position_quantity)
                    )
                    perp_quantity = Decimal(
                        str(open_result.execution.orders[1].filled_quantity or self.position_quantity)
                    )
                # 开仓成功后，把该头寸写入活跃状态，供后续 run_once 持续监控。
                self.active_positions[key] = ActiveFundingArb(
                    workflow_id=key,
                    exchange=opportunity.exchange,
                    symbol=opportunity.symbol,
                    spot_quantity=spot_quantity,
                    perp_quantity=perp_quantity,
                    opened_at=current_time,
                    route=open_result.route,
                    state=StrategyState(is_open=True, opened_at=current_time, hedge_ratio=Decimal("1")),
                )
                self._monitor_state_signatures[key] = MonitorStateSignature(status=WorkflowStatus.OPEN)
            else:
                # 开仓未成功时不能占用名额，避免后续标的被错误阻塞。
                self.manager.release_slot(key)

        return FundingArbRunResult(
            scan=scan_result,
            opened=opened,
            closed=closed,
            active=list(self.active_positions.values()),
        )

    async def _open_position(
        self,
        opportunity: FundingOpportunity,
        snapshot: MarketSnapshot,
        now: datetime,
    ) -> OpenPositionResult:
        """执行一次开仓工作流，并把过程/结果落到 pipeline。

        这里会先记录 workflow 进入 opening 状态，再调用开仓 workflow。
        如果最终开仓成功，还会把订单、成交和持仓快照一起持久化。
        """

        workflow_id = self._key(opportunity.exchange, opportunity.symbol)
        # 开仓前先把 workflow 状态写入 pipeline，便于外部观测执行进度。
        self.pipeline.record_workflow_state(
            workflow_id=workflow_id,
            workflow_type=self.strategy_name,
            exchange=opportunity.exchange,
            symbol=opportunity.symbol,
            status=WorkflowStatus.OPENING,
            payload={"net_rate": str(opportunity.net_rate)},
        )
        result = await self.open_workflow.execute(
            OpenPositionRequest(
                symbol=opportunity.symbol,
                quantity=self.position_quantity,
                funding_rate=opportunity.gross_rate,
                funding_interval_hours=opportunity.funding_interval_hours,
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
        # 无论成功还是失败，都记录开仓结果，便于排查失败原因和重试情况。
        self.pipeline.record_workflow_state(
            workflow_id=workflow_id,
            workflow_type=self.strategy_name,
            exchange=opportunity.exchange,
            symbol=opportunity.symbol,
            status=WorkflowStatus.OPEN if result.status == OpenPositionStatus.OPENED else result.status,
            payload={"reason": result.reason, "attempts": result.attempts, "opened_at": now.isoformat()},
        )
        if result.execution is not None and result.status == OpenPositionStatus.OPENED:
            # 只有真正有执行结果且开仓成功时，才记录订单/成交和持仓对。
            self._persist_execution(result.execution)
            self._persist_position_pair(
                exchange=opportunity.exchange,
                symbol=opportunity.symbol,
                spot_quantity=self.position_quantity,
                perp_quantity=self.position_quantity,
                spot_entry=snapshot.ticker.ask,
                perp_entry=snapshot.ticker.bid,
            )
        return result

    async def _close_position(
        self,
        position: ActiveFundingArb,
        snapshot: MarketSnapshot,
        *,
        reason: str,
        alerts: Sequence[RiskAlert] | None = None,
    ) -> ClosePositionResult:
        """执行一次平仓工作流，并同步更新 pipeline 中的状态和持仓快照。

        平仓时会把现有持仓数量、当前反向报价、资金费率和关闭原因一并传给 workflow，
        让 workflow 按统一规则完成退出。
        """

        closing_payload: dict[str, SerializableValue] = {"reason": reason}
        if alerts is not None:
            closing_payload.update(self._monitor_alert_payload(alerts))
        # 先记录 workflow 进入 closing 阶段，方便日志和状态面板展示。
        self.pipeline.record_workflow_state(
            workflow_id=position.workflow_id,
            workflow_type=self.strategy_name,
            exchange=position.exchange,
            symbol=position.symbol,
            status=WorkflowStatus.CLOSING,
            payload=closing_payload,
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
                funding_rate=(
                    self.strategy.normalize_funding_rate(
                        snapshot.funding.rate,
                        interval_hours=snapshot.funding.funding_interval_hours,
                    )
                    if snapshot.funding is not None
                    else Decimal("0")
                ),
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
        closed_payload: dict[str, SerializableValue] = {
            "reason": result.reason,
            "retries": result.retries,
            "remaining_spot_quantity": str(result.remaining_spot_quantity),
            "remaining_perp_quantity": str(result.remaining_perp_quantity),
        }
        if alerts is not None:
            closed_payload.update(self._monitor_alert_payload(alerts))
        # 将平仓结果按真实状态写回 pipeline，避免把 reduced 误报成 closed。
        self.pipeline.record_workflow_state(
            workflow_id=position.workflow_id,
            workflow_type=self.strategy_name,
            exchange=position.exchange,
            symbol=position.symbol,
            status=result.status,
            payload=closed_payload,
        )
        if result.execution is not None and result.status == ClosePositionStatus.CLOSED:
            # 完全平仓后，同时记录实际执行和“数量归零”的持仓快照。
            self._persist_execution(result.execution)
            self._persist_position_pair(
                exchange=position.exchange,
                symbol=position.symbol,
                spot_quantity=Decimal("0"),
                perp_quantity=Decimal("0"),
                spot_entry=snapshot.ticker.bid,
                perp_entry=snapshot.ticker.ask,
            )
        elif result.execution is not None and result.status == ClosePositionStatus.REDUCED:
            # 部分减仓时保留剩余数量，后续 run_once 会继续监控残余风险。
            self._persist_execution(result.execution)
            self._persist_position_pair(
                exchange=position.exchange,
                symbol=position.symbol,
                spot_quantity=result.remaining_spot_quantity,
                perp_quantity=result.remaining_perp_quantity,
                spot_entry=snapshot.ticker.bid,
                perp_entry=snapshot.ticker.ask,
            )
        return result

    def _record_monitor_state(
        self,
        position: ActiveFundingArb,
        decision: PositionMonitorDecision,
    ) -> None:
        """把当前持仓的风险监控结果写回 workflow 状态，便于外部观测。"""

        signature = MonitorStateSignature(
            status=WorkflowStatus.WARNING if decision.alerts else WorkflowStatus.OPEN,
            alert_reasons=tuple(sorted(str(alert.reason) for alert in decision.alerts)),
        )
        if self._monitor_state_signatures.get(position.workflow_id) == signature:
            return
        self.pipeline.record_workflow_state(
            workflow_id=position.workflow_id,
            workflow_type=self.strategy_name,
            exchange=position.exchange,
            symbol=position.symbol,
            status=signature.status,
            payload={
                "opened_at": position.opened_at.isoformat(),
                **self._monitor_alert_payload(decision.alerts),
            },
        )
        self._monitor_state_signatures[position.workflow_id] = signature

    def _monitor_alert_payload(self, alerts: Sequence[RiskAlert]) -> dict[str, SerializableValue]:
        """把监控告警统一序列化成可持久化的 payload 结构。"""

        return {
            "alert_count": len(alerts),
            "alerts": [
                {
                    "reason": str(alert.reason),
                    "severity": str(alert.severity),
                }
                for alert in alerts
            ],
        }

    def _key(self, exchange: str, symbol: str) -> str:
        """生成服务内部唯一 key，用于索引 workflow 和活跃仓位。"""

        return f"{self.strategy_name}:{exchange}:{symbol}"

    def _snapshot_index(self, snapshots: list[MarketSnapshot]) -> dict[tuple[str, str], MarketSnapshot]:
        """把扫描得到的快照按 `(exchange, symbol)` 建立索引。

        这里只索引带 funding 信息的快照，因为资金费率套利逻辑依赖 funding 字段。
        """

        indexed: dict[tuple[str, str], MarketSnapshot] = {}
        for snapshot in snapshots:
            funding = snapshot.funding
            if funding is None:
                continue
            indexed[(funding.exchange, funding.symbol)] = snapshot
        return indexed

    def _coerce_scan_result(
        self,
        payload: RealtimeScanResult | Mapping[str, object],
    ) -> RealtimeScanResult:
        """把扫描结果统一转换成 `RealtimeScanResult`。

        这个兼容层主要用于吸收不同调用方返回的数据形状：
        - 已经是强类型对象时，直接返回
        - 是字典时，则尽量从 `snapshots` / `opportunities` / `output` 中提取合法字段
        """

        if isinstance(payload, RealtimeScanResult):
            return payload
        raw_snapshots = payload.get("snapshots", [])
        raw_opportunities = payload.get("opportunities", [])
        raw_output = payload.get("output", [])
        # 字符串虽然也是 Sequence，但这里不应被当作列表处理，因此要显式排除。
        snapshot_items = raw_snapshots if isinstance(raw_snapshots, Sequence) and not isinstance(raw_snapshots, str) else []
        opportunity_items = (
            raw_opportunities
            if isinstance(raw_opportunities, Sequence) and not isinstance(raw_opportunities, str)
            else []
        )
        output_items = raw_output if isinstance(raw_output, Sequence) and not isinstance(raw_output, str) else []
        # 支持混合输入：已经是 MarketSnapshot 的直接保留，是 Mapping 的则转成强类型对象。
        snapshots = [
            coerce_market_snapshot(dict(item)) if isinstance(item, Mapping) else item
            for item in snapshot_items
            if isinstance(item, (MarketSnapshot, Mapping))
        ]
        # 候选机会目前只接受 FundingOpportunity，其他类型一律忽略。
        opportunities = [item for item in opportunity_items if isinstance(item, FundingOpportunity)]
        # output 统一转字符串，便于日志/终端展示。
        output = [str(item) for item in output_items]
        return RealtimeScanResult(
            snapshots=snapshots,
            opportunities=opportunities,
            output=output,
        )

    def _persist_execution(self, execution: ExecutionResult) -> None:
        """把一次执行产生的订单和成交明细写入 pipeline。"""

        # 主订单和调整订单都按订单事件记录，成交则单独按 fill 记录。
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
        spot_quantity: Decimal,
        perp_quantity: Decimal,
        spot_entry: Decimal,
        perp_entry: Decimal,
    ) -> None:
        """把一组现货/合约对冲仓位快照写入 pipeline。

        这里按两条腿分别记录数量，避免部分减仓后把剩余风险误写成完全归零。
        """

        # 资金费率套利的现货腿固定记为做多。
        self.pipeline.record_position(
            Position(
                exchange=exchange,
                symbol=symbol,
                market_type=MarketType.SPOT,
                direction=PositionDirection.LONG,
                quantity=spot_quantity,
                entry_price=spot_entry,
                mark_price=spot_entry,
            )
        )
        # 合约腿固定记为做空，形成 spot long + perp short 的对冲结构。
        self.pipeline.record_position(
            Position(
                exchange=exchange,
                symbol=symbol,
                market_type=MarketType.PERPETUAL,
                direction=PositionDirection.SHORT,
                quantity=perp_quantity,
                entry_price=perp_entry,
                mark_price=perp_entry,
            )
        )
