"""Close and emergency de-risking workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from collections.abc import Mapping

from arb.execution.executor import ExecutionLeg, ExecutionResult, PairExecutor
from arb.execution.router import ExecutionRouter, RouteDecision
from arb.models import MarketType, Side
from arb.risk.checks import RiskAlert, RiskChecker, RiskReason
from arb.risk.killswitch import KillSwitch
from arb.workflows.components import (
    DefaultVenueResolver,
    DefaultWorkflowRoutePlanner,
    RoutePlanningRequest,
    VenueResolver,
    WorkflowRoutePlanner,
)
from arb.workflows.open_position import VenueClients


@dataclass(slots=True, frozen=True)
class ClosePositionRequest:
    """单交易所平仓请求。

    这个请求描述的是同一交易所上的一组现货多头 + 永续空头对冲仓位如何退出。
    工作流会根据这里的参数决定走普通平仓还是紧急 reduce-only 去风险模式。
    """

    # 需要平仓的交易标的。
    symbol: str
    # 现货腿待卖出的数量。
    spot_quantity: Decimal
    # 永续腿待买回的数量。
    perp_quantity: Decimal
    # 当前现货参考价格，通常用于生成卖出报价。
    spot_price: Decimal
    # 当前永续参考价格，通常用于生成买回报价。
    perp_price: Decimal
    # 各交易所的客户端集合，供工作流根据路由结果取用。
    venue_clients: Mapping[str, VenueClients]
    # 首选执行交易所。
    preferred_exchange: str
    # 首选交易所不可用时的备选交易所。
    fallback_exchange: str | None = None
    # 首选交易所当前是否可用。
    exchange_available: bool = True
    # 当前资金费率，可用于判断是否已经出现反转。
    funding_rate: Decimal | None = None
    # 最低可接受资金费率，低于该值可能触发平仓。
    min_expected_rate: Decimal = Decimal("0")
    # 开仓时间，用于检查持仓时长是否超限。
    opened_at: datetime | None = None
    # 最大持仓时长。
    max_holding_period: timedelta | None = None
    # 显式指定的平仓原因；未提供时由风控/kill switch 推导。
    close_reason: str | None = None
    # 是否强制只允许 reduce-only 模式。
    reduce_only_only: bool = False
    # maker 手续费率，用于路由决策。
    maker_fee_rate: Decimal = Decimal("0")
    # taker 手续费率，用于路由决策。
    taker_fee_rate: Decimal = Decimal("0")
    # 当前价差，单位 bps，用于路由评估。
    spread_bps: Decimal = Decimal("5")
    # 允许的最大滑点，单位 bps。
    max_slippage_bps: Decimal = Decimal("5")
    # 初次平仓失败后的最大重试次数。
    max_retries: int = 1


@dataclass(slots=True, frozen=True)
class CrossExchangeCloseRequest:
    """跨交易所平仓请求。

    这个请求用于处理一条腿在交易所 A、另一条腿在交易所 B 的情况，
    因此会分别给出 long / short 所在交易所及其数量与价格。
    """

    # 需要退出的交易标的。
    symbol: str
    # 多头腿所在交易所。
    long_exchange: str
    # 空头腿所在交易所。
    short_exchange: str
    # 多头腿待平数量。
    long_quantity: Decimal
    # 空头腿待平数量。
    short_quantity: Decimal
    # 多头腿参考价格。
    long_price: Decimal
    # 空头腿参考价格。
    short_price: Decimal
    # 可用交易所客户端映射。
    venue_clients: Mapping[str, VenueClients]
    # 平仓原因。
    close_reason: str | None = None
    # maker 手续费率。
    maker_fee_rate: Decimal = Decimal("0")
    # taker 手续费率。
    taker_fee_rate: Decimal = Decimal("0")
    # 当前价差，单位 bps。
    spread_bps: Decimal = Decimal("5")
    # 最大允许滑点，单位 bps。
    max_slippage_bps: Decimal = Decimal("5")
    # 是否强制 reduce-only。
    reduce_only_only: bool = False


@dataclass(slots=True)
class ClosePositionResult:
    """平仓工作流执行结果。"""

    # 工作流最终状态，例如 closed / reduced / failed。
    status: str
    # 结果原因，用于日志与上层编排。
    reason: str
    # 本次执行采用的路由决策。
    route: RouteDecision | None = None
    # 实际执行结果，包含订单、成交和执行状态。
    execution: ExecutionResult | None = None
    # 重试次数。
    retries: int = 0
    # 平仓前识别出的风控告警。
    alerts: list[RiskAlert] = field(default_factory=list)
    # 现货腿剩余待平数量；完全平仓时为 0。
    remaining_spot_quantity: Decimal = Decimal("0")
    # 永续腿剩余待平数量；完全平仓时为 0。
    remaining_perp_quantity: Decimal = Decimal("0")


class ClosePositionWorkflow:
    """协调普通平仓与紧急去风险平仓的工作流。

    它的职责不是直接决定“要不要平仓”，而是在上层已经决定退出后，
    负责选择路由、构造执行腿、处理重试，并将结果汇总成统一输出。
    """

    def __init__(
        self,
        *,
        executor: PairExecutor | None = None,
        router: ExecutionRouter | None = None,
        route_planner: WorkflowRoutePlanner | None = None,
        venue_resolver: VenueResolver[VenueClients] | None = None,
        risk_checker: RiskChecker | None = None,
        kill_switch: KillSwitch | None = None,
    ) -> None:
        self.executor = executor or PairExecutor()
        self.router = router or ExecutionRouter()
        self.route_planner = route_planner or DefaultWorkflowRoutePlanner(self.router)
        self.venue_resolver = venue_resolver or DefaultVenueResolver()
        self.risk_checker = risk_checker or RiskChecker()
        self.kill_switch = kill_switch or KillSwitch()

    async def execute(self, request: ClosePositionRequest) -> ClosePositionResult:
        """执行单交易所平仓。

        流程大致如下：
        1. 先根据资金费率反转、持仓超时、kill switch 等条件收集风险告警
        2. 推导平仓原因，并判断是否进入紧急 reduce-only 模式
        3. 先按当前路由尝试完整平仓
        4. 若未完全成功，则根据剩余数量切换到更激进的 urgent 路由继续重试
        """

        # 收集平仓前的风险信号，这些信息会一起回传给上层。
        alerts = self._alerts(request)
        # 若调用方没有显式给出原因，则由风险检查和 kill switch 推导默认原因。
        reason = request.close_reason or self.kill_switch.close_reason(
            self.risk_checker.choose_close_reason(alerts)
        )
        # 紧急模式下通常会偏向 reduce-only、taker 或更保守的路由策略。
        urgent = self.kill_switch.requires_reduce_only() or request.reduce_only_only
        route = self._route(request, urgent=urgent)

        # 首次尝试使用原始数量完整平仓。
        execution = await self._attempt(
            request,
            route,
            spot_quantity=request.spot_quantity,
            perp_quantity=request.perp_quantity,
            reduce_only=request.reduce_only_only or self.kill_switch.requires_reduce_only(),
        )
        remaining_spot = self._remaining_quantity(execution, 0, request.spot_quantity)
        remaining_perp = self._remaining_quantity(execution, 1, request.perp_quantity)
        retries = 0
        if self._is_success(execution) and self._is_fully_closed(remaining_spot, remaining_perp):
            return ClosePositionResult(
                status="closed",
                reason=reason,
                route=route,
                execution=execution,
                retries=retries,
                alerts=alerts,
                remaining_spot_quantity=remaining_spot,
                remaining_perp_quantity=remaining_perp,
            )

        # 首次尝试失败后，根据已成交情况计算剩余待平数量。
        while retries < request.max_retries and (remaining_spot > 0 or remaining_perp > 0):
            # 重试阶段一律按 urgent 模式处理，目标从“优雅退出”转为“尽快去风险”。
            route = self._route(request, urgent=True)
            execution = await self._attempt(
                request,
                route,
                spot_quantity=remaining_spot,
                perp_quantity=remaining_perp,
                reduce_only=True,
            )
            retries += 1
            remaining_spot = self._remaining_quantity(execution, 0, remaining_spot)
            remaining_perp = self._remaining_quantity(execution, 1, remaining_perp)
            if self._is_success(execution) and self._is_fully_closed(remaining_spot, remaining_perp):
                return ClosePositionResult(
                    status="closed",
                    reason=reason,
                    route=route,
                    execution=execution,
                    retries=retries,
                    alerts=alerts,
                    remaining_spot_quantity=remaining_spot,
                    remaining_perp_quantity=remaining_perp,
                )
        if self._has_reduction(
            request=request,
            remaining_spot=remaining_spot,
            remaining_perp=remaining_perp,
        ):
            return ClosePositionResult(
                status="reduced",
                reason=reason,
                route=route,
                execution=execution,
                retries=retries,
                alerts=alerts,
                remaining_spot_quantity=remaining_spot,
                remaining_perp_quantity=remaining_perp,
            )

        return ClosePositionResult(
            status="failed",
            reason=reason,
            route=route,
            execution=execution,
            retries=retries,
            alerts=alerts,
            remaining_spot_quantity=remaining_spot,
            remaining_perp_quantity=remaining_perp,
        )

    async def execute_cross_exchange(self, request: CrossExchangeCloseRequest) -> ClosePositionResult:
        """执行跨交易所平仓。

        这里的 long / short 两条腿都在永续市场上，只是分布在不同交易所。
        因为目标是尽快退出风险敞口，所以默认以 urgent 模式进行路由。
        """

        route = self.route_planner.plan(
            RoutePlanningRequest(
                preferred_exchange=request.short_exchange,
                fallback_exchange=request.long_exchange,
                exchange_available=True,
                urgent=True,
                maker_fee_rate=request.maker_fee_rate,
                taker_fee_rate=request.taker_fee_rate,
                spread_bps=request.spread_bps,
            )
        )
        long_venue = self.venue_resolver.resolve(request.venue_clients, request.long_exchange)
        short_venue = self.venue_resolver.resolve(request.venue_clients, request.short_exchange)
        # 任意一条腿缺少客户端时，都无法继续执行。
        if long_venue is None or short_venue is None:
            missing = request.long_exchange if long_venue is None else request.short_exchange
            return ClosePositionResult(
                status="failed",
                reason=f"missing venue: {missing}",
                route=route,
            )

        # 多头腿平仓需要卖出对应合约。
        long_leg = ExecutionLeg(
            client=long_venue.perp_client,
            symbol=request.symbol,
            market_type=MarketType.PERPETUAL,
            side=Side.SELL.value,
            quantity=request.long_quantity,
            price=self.router.quote_price(
                reference_price=request.long_price,
                side=Side.SELL,
                mode=route.mode,
                max_slippage_bps=request.max_slippage_bps,
            ),
            reduce_only=request.reduce_only_only or request.long_quantity > 0,
            context=long_venue.perp_context,
        )
        # 空头腿平仓需要买回对应合约。
        short_leg = ExecutionLeg(
            client=short_venue.perp_client,
            symbol=request.symbol,
            market_type=MarketType.PERPETUAL,
            side=Side.BUY.value,
            quantity=request.short_quantity,
            price=self.router.quote_price(
                reference_price=request.short_price,
                side=Side.BUY,
                mode=route.mode,
                max_slippage_bps=request.max_slippage_bps,
            ),
            reduce_only=True,
            context=short_venue.perp_context,
        )
        execution = await self.executor.execute_pair(long_leg, short_leg)
        if execution.status in {"filled", "adjusted"}:
            return ClosePositionResult(
                status="closed",
                reason=request.close_reason or "spread_compressed",
                route=route,
                execution=execution,
            )
        return ClosePositionResult(
            status="failed",
            reason=request.close_reason or execution.reason or "close_failed",
            route=route,
            execution=execution,
        )

    async def _attempt(
        self,
        request: ClosePositionRequest,
        route: RouteDecision,
        *,
        spot_quantity: Decimal,
        perp_quantity: Decimal,
        reduce_only: bool,
    ) -> ExecutionResult:
        """按给定路由尝试一次平仓。

        该方法既处理双腿同时平仓，也处理只剩单腿待平的情况。
        返回的 `ExecutionResult` 会被上层用于判断是否需要重试以及剩余数量。
        """

        venue = self.venue_resolver.resolve(request.venue_clients, route.exchange)
        if venue is None:
            return ExecutionResult(status="failed", reason=f"missing venue: {route.exchange}")
        # 两条腿都已经没有剩余数量时，直接视作成功完成。
        if spot_quantity <= 0 and perp_quantity <= 0:
            return ExecutionResult(status="filled")
        # 现货腿平仓即卖出现货。
        spot_leg = ExecutionLeg(
            client=venue.spot_client,
            symbol=request.symbol,
            market_type=MarketType.SPOT,
            side=Side.SELL.value,
            quantity=spot_quantity,
            price=self.router.quote_price(
                reference_price=request.spot_price,
                side=Side.SELL,
                mode=route.mode,
                max_slippage_bps=request.max_slippage_bps,
            ),
            context=venue.spot_context,
        )
        # 永续空头平仓即买回合约；reduce_only 用于防止误加仓。
        perp_leg = ExecutionLeg(
            client=venue.perp_client,
            symbol=request.symbol,
            market_type=MarketType.PERPETUAL,
            side=Side.BUY.value,
            quantity=perp_quantity,
            price=self.router.quote_price(
                reference_price=request.perp_price,
                side=Side.BUY,
                mode=route.mode,
                max_slippage_bps=request.max_slippage_bps,
            ),
            reduce_only=True if reduce_only or perp_quantity > 0 else False,
            context=venue.perp_context,
        )
        if spot_quantity <= 0 or perp_quantity <= 0:
            # 只剩一条腿时，退化为单腿下单 + 订单跟踪。
            leg = perp_leg if spot_quantity <= 0 else spot_leg
            order = await leg.client.create_order(
                leg.symbol,
                leg.market_type,
                leg.side,
                leg.quantity,
                price=leg.price,
                reduce_only=leg.reduce_only,
            )
            tracked = await self.executor.tracker.track_order(
                leg.client,
                order,
                symbol=leg.symbol,
                market_type=leg.market_type,
            )
            status = "filled"
            # 如果超时且完全没有成交，则按失败处理；部分成交则标记为 partial，交给上层继续减仓。
            if tracked.timed_out and tracked.final_order.filled_quantity == 0:
                status = "failed"
            elif tracked.final_order.remaining_quantity > 0:
                status = "partial"
            return ExecutionResult(
                status=status,
                orders=[tracked.final_order],
                reason="" if status == "filled" else "close_failed",
            )
        # 两条腿都还存在时，交给配对执行器做联动执行。
        execution = await self.executor.execute_pair(spot_leg, perp_leg)
        if execution.status == "failed" and not execution.reason:
            # 给失败结果补上统一的默认原因，方便上层处理。
            execution.reason = "close_failed"
        return execution

    def _route(self, request: ClosePositionRequest, *, urgent: bool) -> RouteDecision:
        """根据当前请求和紧急程度生成执行路由。"""

        return self.route_planner.plan(
            RoutePlanningRequest(
                preferred_exchange=request.preferred_exchange,
                fallback_exchange=request.fallback_exchange,
                exchange_available=request.exchange_available,
                urgent=urgent,
                maker_fee_rate=request.maker_fee_rate,
                taker_fee_rate=request.taker_fee_rate,
                spread_bps=request.spread_bps,
            )
        )

    def _alerts(self, request: ClosePositionRequest) -> list[RiskAlert]:
        """根据请求上下文收集平仓相关的风险告警。"""

        alerts: list[RiskAlert] = []
        # kill switch 激活时，无条件追加高优先级告警。
        if self.kill_switch.active:
            alerts.append(RiskAlert(RiskReason.KILLSWITCH_ACTIVE, request.symbol))
        if request.funding_rate is not None:
            # 资金费率低于预期时，可能说明策略边际收益消失或反转。
            alert = self.risk_checker.check_funding_reversal(
                symbol=request.symbol,
                current_rate=request.funding_rate,
                min_expected_rate=request.min_expected_rate,
            )
            if alert is not None:
                alerts.append(alert)
        if request.max_holding_period is not None:
            # 持仓时间超过上限时，需要考虑退出避免长期暴露。
            alert = self.risk_checker.check_holding_period(
                symbol=request.symbol,
                opened_at=request.opened_at,
                max_holding_period=request.max_holding_period,
            )
            if alert is not None:
                alerts.append(alert)
        return alerts

    def _remaining_quantity(
        self,
        execution: ExecutionResult,
        index: int,
        default: Decimal,
    ) -> Decimal:
        """根据执行结果计算某一条腿的剩余待平数量。

        `index` 对应订单列表里的腿顺序；若该腿没有返回订单，则保守地沿用默认数量。
        """

        if execution.status == "adjusted":
            # 已经提交过补单时，当前工作流把该腿视为已交给调整单收口，不再继续重复下相同数量。
            return Decimal("0")
        if len(execution.orders) <= index:
            return default
        order = execution.orders[index]
        return max(Decimal(str(order.quantity)) - Decimal(str(order.filled_quantity)), Decimal("0"))

    def _has_reduction(
        self,
        *,
        request: ClosePositionRequest,
        remaining_spot: Decimal,
        remaining_perp: Decimal,
    ) -> bool:
        """判断本次平仓是否至少缩小了部分风险敞口。"""

        return remaining_spot < request.spot_quantity or remaining_perp < request.perp_quantity

    def _is_fully_closed(self, remaining_spot: Decimal, remaining_perp: Decimal) -> bool:
        """判断现货腿和永续腿是否都已经完全退出。"""

        return remaining_spot <= 0 and remaining_perp <= 0

    def _is_success(self, execution: ExecutionResult) -> bool:
        """判断本次执行是否可视为成功结束。"""

        return execution.status in {"filled", "adjusted"}
