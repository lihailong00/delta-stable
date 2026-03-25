"""开仓工作流：负责现货做多、永续做空的资金费率套利入场执行。"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from arb.funding import DEFAULT_FUNDING_INTERVAL_HOURS
from arb.execution.executor import ExecutionLeg, ExecutionResult, ExecutionStatus, PairExecutor
from arb.execution.guards import GuardContext
from arb.execution.protocols import ClockFn, CreateOrderClient
from arb.execution.router import ExecutionRouter, RouteDecision, RouteMode
from arb.models import MarketType, Order, Side
from arb.strategy.spot_perp import SpotPerpInputs, SpotPerpStrategy
from arb.workflows.components import (
    DefaultVenueResolver,
    DefaultWorkflowRoutePlanner,
    RoutePlanningRequest,
    VenueResolver,
    WorkflowRoutePlanner,
)
from arb.workflows.enums import OpenPositionStatus


@dataclass(slots=True, frozen=True)
class VenueClientBundle:
    """单个交易所开仓所需的客户端与风控上下文。"""

    # 交易所标识，例如 binance / okx。
    exchange: str
    # 现货下单客户端。
    spot_client: CreateOrderClient
    # 永续下单客户端。
    perp_client: CreateOrderClient
    # 现货腿下单前的余额/交易对校验上下文。
    spot_context: GuardContext | None = None
    # 永续腿下单前的余额/交易对校验上下文。
    perp_context: GuardContext | None = None


@dataclass(slots=True, frozen=True)
class OpenPositionRequest:
    """单交易所开仓请求。

    该请求描述同一交易所上的“现货买入 + 永续卖出”开仓动作，
    包括目标数量、参考价格、路由条件与失败后的退路策略。
    """

    # 交易标的。
    symbol: str
    # 两条腿的目标开仓数量。
    quantity: Decimal
    # 当前资金费率，用于策略判断是否值得开仓。
    funding_rate: Decimal
    # 现货腿参考价格。
    spot_price: Decimal
    # 永续腿参考价格。
    perp_price: Decimal
    # 可用交易所客户端映射。
    venue_clients: Mapping[str, VenueClientBundle]
    # 首选交易所。
    preferred_exchange: str
    # 资金费率对应的周期，用于归一化收益判断。
    funding_interval_hours: int = DEFAULT_FUNDING_INTERVAL_HOURS
    # 首选交易所不可用时的备选交易所。
    fallback_exchange: str | None = None
    # 首选交易所当前是否可下单。
    exchange_available: bool = True
    # maker 手续费率，供路由器比较成本。
    maker_fee_rate: Decimal = Decimal("0")
    # taker 手续费率，供路由器比较成本。
    taker_fee_rate: Decimal = Decimal("0")
    # 当前价差，单位 bps，用于决定是否值得走 maker。
    spread_bps: Decimal = Decimal("5")
    # taker 报价允许的最大滑点，单位 bps。
    max_slippage_bps: Decimal = Decimal("5")
    # 裸腿暴露可容忍的最长时间。
    max_naked_seconds: float = 2.0
    # 首次失败后是否允许切换到 taker 再试一次。
    allow_taker_fallback: bool = True


@dataclass(slots=True, frozen=True)
class CrossExchangeOpenRequest:
    """跨交易所开仓请求。

    该场景不再是一现货一永续，而是分别在不同交易所上做一多一空两条永续腿，
    因此会显式给出 long / short 所在交易所及各自参考价格。
    """

    # 交易标的。
    symbol: str
    # 两条腿的目标开仓数量。
    quantity: Decimal
    # 做多腿所在交易所。
    long_exchange: str
    # 做空腿所在交易所。
    short_exchange: str
    # 做多腿参考价格。
    long_price: Decimal
    # 做空腿参考价格。
    short_price: Decimal
    # 可用交易所客户端映射。
    venue_clients: Mapping[str, VenueClientBundle]
    # maker 手续费率。
    maker_fee_rate: Decimal = Decimal("0")
    # taker 手续费率。
    taker_fee_rate: Decimal = Decimal("0")
    # 当前价差，单位 bps。
    spread_bps: Decimal = Decimal("5")
    # 最大允许滑点，单位 bps。
    max_slippage_bps: Decimal = Decimal("5")
    # 是否直接按紧急模式路由。
    urgent: bool = False


@dataclass(slots=True)
class OpenPositionResult:
    """开仓工作流输出结果。"""

    # 工作流最终状态，例如 opened / rejected / rolled_back / failed。
    status: OpenPositionStatus
    # 结果原因，供上层日志与状态机使用。
    reason: str
    # 本次执行采用的路由决策。
    route: RouteDecision | None = None
    # 执行器返回的底层执行结果。
    execution: ExecutionResult | None = None
    # 开仓失败后为了消除裸腿而发出的回滚订单。
    rollback_orders: list[Order] = field(default_factory=list)
    # 实际尝试次数，包含 taker fallback。
    attempts: int = 0


class OpenPositionWorkflow:
    """负责将一次开仓动作完整编排出来。

    它的职责不是判断“策略上该不该开仓”，而是在上层已经决定尝试开仓后，
    把报价校验、路由选择、双腿执行、taker fallback 与失败回滚串成一个完整流程。
    """

    def __init__(
        self,
        *,
        strategy: SpotPerpStrategy | None = None,
        executor: PairExecutor | None = None,
        router: ExecutionRouter | None = None,
        route_planner: WorkflowRoutePlanner | None = None,
        venue_resolver: VenueResolver[VenueClientBundle] | None = None,
        clock: ClockFn | None = None,
    ) -> None:
        self.strategy = strategy or SpotPerpStrategy()
        self.executor = executor or PairExecutor()
        self.router = router or ExecutionRouter()
        self.route_planner = route_planner or DefaultWorkflowRoutePlanner(self.router)
        self.venue_resolver = venue_resolver or DefaultVenueResolver()
        self.clock = clock or time.monotonic

    async def execute(self, request: OpenPositionRequest) -> OpenPositionResult:
        """执行单交易所开仓。

        流程分为四步：
        1. 先用策略层校验当前资金费率和报价是否值得开仓
        2. 走首轮路由并尝试执行双腿订单
        3. 如果允许且有必要，则切到 taker 路由再试一次
        4. 若仍失败且已经形成裸腿，则发起回滚订单消除敞口
        """

        # 先做策略层报价检查，避免在不满足收益阈值时进入执行链路。
        quote_check = self.strategy.check_entry_quote(
            SpotPerpInputs(
                symbol=request.symbol,
                funding_rate=request.funding_rate,
                funding_interval_hours=request.funding_interval_hours,
                spot_price=request.spot_price,
                perp_price=request.perp_price,
            )
        )
        if not quote_check.accepted:
            return OpenPositionResult(status=OpenPositionStatus.REJECTED, reason=quote_check.reason)

        # 记录开始时间，用于后续判断是否已经超过可容忍的裸腿时间。
        started_at = float(self.clock())
        # 首次尝试优先走常规路由，通常是更便宜的 maker 模式。
        route = self._route(request, urgent=False)
        execution = await self._attempt(request, route)
        attempts = 1

        if self._is_success(execution):
            return OpenPositionResult(
                status=OpenPositionStatus.OPENED,
                reason="opened",
                route=route,
                execution=execution,
                attempts=attempts,
            )

        elapsed = float(self.clock()) - started_at
        if (
            request.allow_taker_fallback
            and self._can_retry_with_taker(request, route, execution, elapsed)
        ):
            # 首次失败且仍适合重试时，切到更激进的 urgent/taker 路由再做一次尝试。
            retry_route = self._route(request, urgent=True)
            retry_execution = await self._attempt(request, retry_route)
            attempts += 1
            if self._is_success(retry_execution):
                return OpenPositionResult(
                    status=OpenPositionStatus.OPENED,
                    reason="opened_after_taker_fallback",
                    route=retry_route,
                    execution=retry_execution,
                    attempts=attempts,
                )
            execution = retry_execution
            route = retry_route
            elapsed = float(self.clock()) - started_at

        # 到这里说明开仓仍未成功，需要判断是否已经形成裸腿并决定是否回滚。
        rollback_orders, rollback_reason = await self._maybe_rollback(
            request,
            route,
            execution,
            elapsed_seconds=elapsed,
        )
        status = OpenPositionStatus.ROLLED_BACK if rollback_orders else OpenPositionStatus.FAILED
        reason = rollback_reason or execution.reason or "open_failed"
        return OpenPositionResult(
            status=status,
            reason=reason,
            route=route,
            execution=execution,
            rollback_orders=rollback_orders,
            attempts=attempts,
        )

    async def execute_cross_exchange(self, request: CrossExchangeOpenRequest) -> OpenPositionResult:
        """执行跨交易所开仓。

        这里会分别在 long / short 交易所构造两条永续腿，
        再交给配对执行器做联动下单与成交跟踪。
        """

        route = self.route_planner.plan(
            RoutePlanningRequest(
                preferred_exchange=request.short_exchange,
                fallback_exchange=request.long_exchange,
                exchange_available=True,
                urgent=request.urgent,
                maker_fee_rate=request.maker_fee_rate,
                taker_fee_rate=request.taker_fee_rate,
                spread_bps=request.spread_bps,
            )
        )
        # 两条腿分别解析各自交易所的客户端；任意一侧缺失都无法继续。
        long_venue = self.venue_resolver.resolve(request.venue_clients, request.long_exchange)
        short_venue = self.venue_resolver.resolve(request.venue_clients, request.short_exchange)
        if long_venue is None or short_venue is None:
            missing = request.long_exchange if long_venue is None else request.short_exchange
            return OpenPositionResult(status=OpenPositionStatus.FAILED, reason=f"missing venue: {missing}", route=route)

        # 做多腿：在 long_exchange 上买入永续。
        long_leg = ExecutionLeg(
            client=long_venue.perp_client,
            symbol=request.symbol,
            market_type=MarketType.PERPETUAL,
            side=Side.BUY.value,
            quantity=request.quantity,
            price=self.router.quote_price(
                reference_price=request.long_price,
                side=Side.BUY,
                mode=route.mode,
                max_slippage_bps=request.max_slippage_bps,
            ),
            context=long_venue.perp_context,
        )
        # 做空腿：在 short_exchange 上卖出永续。
        short_leg = ExecutionLeg(
            client=short_venue.perp_client,
            symbol=request.symbol,
            market_type=MarketType.PERPETUAL,
            side=Side.SELL.value,
            quantity=request.quantity,
            price=self.router.quote_price(
                reference_price=request.short_price,
                side=Side.SELL,
                mode=route.mode,
                max_slippage_bps=request.max_slippage_bps,
            ),
            context=short_venue.perp_context,
        )
        execution = await self.executor.execute_pair(long_leg, short_leg)
        # filled / adjusted 都视为开仓成功；adjusted 表示执行器内部已经做过补偿调整。
        if execution.status in {ExecutionStatus.FILLED, ExecutionStatus.ADJUSTED}:
            return OpenPositionResult(
                status=OpenPositionStatus.OPENED,
                reason="opened",
                route=route,
                execution=execution,
                attempts=1,
            )
        return OpenPositionResult(
            status=OpenPositionStatus.FAILED,
            reason=execution.reason or "open_failed",
            route=route,
            execution=execution,
            attempts=1,
        )

    async def _attempt(
        self,
        request: OpenPositionRequest,
        route: RouteDecision,
    ) -> ExecutionResult:
        """按给定路由尝试一次单交易所开仓。"""

        # 根据路由结果解析交易所客户端；路由命中了不存在的交易所时直接失败。
        venue = self.venue_resolver.resolve(request.venue_clients, route.exchange)
        if venue is None:
            return ExecutionResult(status=ExecutionStatus.FAILED, reason=f"missing venue: {route.exchange}")
        # 现货腿负责买入底仓。
        spot_leg = ExecutionLeg(
            client=venue.spot_client,
            symbol=request.symbol,
            market_type=MarketType.SPOT,
            side=Side.BUY.value,
            quantity=request.quantity,
            price=self.router.quote_price(
                reference_price=request.spot_price,
                side=Side.BUY,
                mode=route.mode,
                max_slippage_bps=request.max_slippage_bps,
            ),
            context=venue.spot_context,
        )
        # 永续腿负责卖出对冲空头。
        perp_leg = ExecutionLeg(
            client=venue.perp_client,
            symbol=request.symbol,
            market_type=MarketType.PERPETUAL,
            side=Side.SELL.value,
            quantity=request.quantity,
            price=self.router.quote_price(
                reference_price=request.perp_price,
                side=Side.SELL,
                mode=route.mode,
                max_slippage_bps=request.max_slippage_bps,
            ),
            context=venue.perp_context,
        )
        execution = await self.executor.execute_pair(spot_leg, perp_leg)
        if execution.status == ExecutionStatus.FAILED and not execution.reason:
            # 统一补上默认失败原因，避免上层拿到空字符串。
            execution.reason = "open_failed"
        return execution

    def _route(self, request: OpenPositionRequest, *, urgent: bool) -> RouteDecision:
        """根据当前请求生成一次开仓路由。"""

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

    def _can_retry_with_taker(
        self,
        request: OpenPositionRequest,
        route: RouteDecision,
        execution: ExecutionResult,
        elapsed_seconds: float,
    ) -> bool:
        """判断是否值得从当前失败结果切到 taker 再试一次。"""

        # 已经是 taker 就没有继续升级的空间了。
        if route.mode == RouteMode.TAKER:
            return False
        # 只有明确失败时才考虑 fallback；部分成功会进入回滚分支。
        if execution.status != ExecutionStatus.FAILED:
            return False
        # 一旦已经形成敞口，优先回滚而不是继续加码重试。
        if self._has_exposure(execution):
            return False
        # 这里返回的是“还没到必须强制 taker 的临界点”，说明可以先再试一次。
        return not self.router.should_escalate_to_taker(
            current_mode=route.mode,
            elapsed_seconds=elapsed_seconds,
            max_naked_seconds=request.max_naked_seconds,
        )

    async def _maybe_rollback(
        self,
        request: OpenPositionRequest,
        route: RouteDecision,
        execution: ExecutionResult,
        *,
        elapsed_seconds: float,
    ) -> tuple[list[Order], str | None]:
        """在开仓失败后决定是否回滚已成交腿，并返回回滚订单列表。"""

        if not self._has_exposure(execution):
            # 没有任何成交时无需回滚；如果等待时间已经过长，则返回裸腿时间超限原因。
            if self.router.should_escalate_to_taker(
                current_mode=route.mode,
                elapsed_seconds=elapsed_seconds,
                max_naked_seconds=request.max_naked_seconds,
            ):
                return [], "naked_time_exceeded"
            return [], execution.reason or None

        venue = self.venue_resolver.resolve(request.venue_clients, route.exchange)
        if venue is None:
            return [], execution.reason or f"missing venue: {route.exchange}"

        rollback_orders: list[Order] = []
        for order in execution.orders:
            # 这里显式转成 Decimal(str(...))，避免不同数值类型混用带来的精度偏差。
            filled_quantity = Decimal(str(getattr(order, "filled_quantity", "0")))
            if filled_quantity <= 0:
                continue
            if order.market_type is MarketType.SPOT:
                # 现货开仓买入后，回滚时需要卖出已成交数量。
                client = venue.spot_client
                side = Side.SELL.value
                reduce_only = False
            else:
                # 永续开仓卖出后，回滚时需要买回，并强制 reduce_only 避免误开反向仓。
                client = venue.perp_client
                side = Side.BUY.value
                reduce_only = True
            rollback_orders.append(
                await client.create_order(
                    order.symbol,
                    order.market_type,
                    side,
                    filled_quantity,
                    price=order.average_price or order.price,
                    reduce_only=reduce_only,
                )
            )
        # 如果等待时间已经超过阈值，优先把原因标记为裸腿暴露超时。
        reason = "naked_time_exceeded" if elapsed_seconds >= request.max_naked_seconds else "rollback_after_open_failure"
        return rollback_orders, reason

    def _has_exposure(self, execution: ExecutionResult) -> bool:
        """判断本次执行是否已经留下任意一条已成交敞口。"""

        return any(order.filled_quantity > 0 for order in execution.orders)

    def _is_success(self, execution: ExecutionResult) -> bool:
        """判断执行结果是否可以视为成功开仓。"""

        return execution.status in {ExecutionStatus.FILLED, ExecutionStatus.ADJUSTED}
