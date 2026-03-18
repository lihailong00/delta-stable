"""Close and emergency de-risking workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from collections.abc import Mapping

from arb.execution.executor import ExecutionLeg, ExecutionResult, PairExecutor
from arb.execution.router import ExecutionRouter, RouteDecision
from arb.models import MarketType, Side
from arb.risk.checks import RiskAlert, RiskChecker
from arb.risk.killswitch import KillSwitch
from arb.workflows.open_position import VenueClients


@dataclass(slots=True, frozen=True)
class ClosePositionRequest:
    symbol: str
    spot_quantity: Decimal
    perp_quantity: Decimal
    spot_price: Decimal
    perp_price: Decimal
    venue_clients: Mapping[str, VenueClients]
    preferred_exchange: str
    fallback_exchange: str | None = None
    exchange_available: bool = True
    funding_rate: Decimal | None = None
    min_expected_rate: Decimal = Decimal("0")
    opened_at: datetime | None = None
    max_holding_period: timedelta | None = None
    close_reason: str | None = None
    reduce_only_only: bool = False
    maker_fee_rate: Decimal = Decimal("0")
    taker_fee_rate: Decimal = Decimal("0")
    spread_bps: Decimal = Decimal("5")
    max_slippage_bps: Decimal = Decimal("5")
    max_retries: int = 1


@dataclass(slots=True, frozen=True)
class CrossExchangeCloseRequest:
    symbol: str
    long_exchange: str
    short_exchange: str
    long_quantity: Decimal
    short_quantity: Decimal
    long_price: Decimal
    short_price: Decimal
    venue_clients: Mapping[str, VenueClients]
    close_reason: str | None = None
    maker_fee_rate: Decimal = Decimal("0")
    taker_fee_rate: Decimal = Decimal("0")
    spread_bps: Decimal = Decimal("5")
    max_slippage_bps: Decimal = Decimal("5")
    reduce_only_only: bool = False


@dataclass(slots=True)
class ClosePositionResult:
    status: str
    reason: str
    route: RouteDecision | None = None
    execution: ExecutionResult | None = None
    retries: int = 0
    alerts: list[RiskAlert] = field(default_factory=list)


class ClosePositionWorkflow:
    """Coordinate normal closes and emergency reduce-only unwinds."""

    def __init__(
        self,
        *,
        executor: PairExecutor | None = None,
        router: ExecutionRouter | None = None,
        risk_checker: RiskChecker | None = None,
        kill_switch: KillSwitch | None = None,
    ) -> None:
        self.executor = executor or PairExecutor()
        self.router = router or ExecutionRouter()
        self.risk_checker = risk_checker or RiskChecker()
        self.kill_switch = kill_switch or KillSwitch()

    async def execute(self, request: ClosePositionRequest) -> ClosePositionResult:
        alerts = self._alerts(request)
        reason = request.close_reason or self.kill_switch.close_reason(
            self.risk_checker.choose_close_reason(alerts)
        )
        urgent = self.kill_switch.requires_reduce_only() or request.reduce_only_only
        route = self._route(request, urgent=urgent)

        execution = await self._attempt(
            request,
            route,
            spot_quantity=request.spot_quantity,
            perp_quantity=request.perp_quantity,
            reduce_only=request.reduce_only_only or self.kill_switch.requires_reduce_only(),
        )
        retries = 0
        if self._is_success(execution):
            return ClosePositionResult(
                status="reduced" if urgent else "closed",
                reason=reason,
                route=route,
                execution=execution,
                retries=retries,
                alerts=alerts,
            )

        remaining_spot = self._remaining_quantity(execution, 0, request.spot_quantity)
        remaining_perp = self._remaining_quantity(execution, 1, request.perp_quantity)
        while retries < request.max_retries and (remaining_spot > 0 or remaining_perp > 0):
            route = self._route(request, urgent=True)
            execution = await self._attempt(
                request,
                route,
                spot_quantity=remaining_spot,
                perp_quantity=remaining_perp,
                reduce_only=True,
            )
            retries += 1
            if self._is_success(execution):
                return ClosePositionResult(
                    status="reduced" if urgent or retries > 0 else "closed",
                    reason=reason,
                    route=route,
                    execution=execution,
                    retries=retries,
                    alerts=alerts,
                )
            remaining_spot = self._remaining_quantity(execution, 0, remaining_spot)
            remaining_perp = self._remaining_quantity(execution, 1, remaining_perp)

        return ClosePositionResult(
            status="failed",
            reason=reason,
            route=route,
            execution=execution,
            retries=retries,
            alerts=alerts,
        )

    async def execute_cross_exchange(self, request: CrossExchangeCloseRequest) -> ClosePositionResult:
        route = self.router.route(
            preferred_exchange=request.short_exchange,
            fallback_exchange=request.long_exchange,
            exchange_available=True,
            urgent=True,
            maker_fee_rate=request.maker_fee_rate,
            taker_fee_rate=request.taker_fee_rate,
            spread_bps=request.spread_bps,
        )
        long_venue = request.venue_clients.get(request.long_exchange)
        short_venue = request.venue_clients.get(request.short_exchange)
        if long_venue is None or short_venue is None:
            missing = request.long_exchange if long_venue is None else request.short_exchange
            return ClosePositionResult(
                status="failed",
                reason=f"missing venue: {missing}",
                route=route,
            )

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
        venue = request.venue_clients.get(route.exchange)
        if venue is None:
            return ExecutionResult(status="failed", reason=f"missing venue: {route.exchange}")
        if spot_quantity <= 0 and perp_quantity <= 0:
            return ExecutionResult(status="filled")
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
            if tracked.timed_out and tracked.final_order.filled_quantity == 0:
                status = "failed"
            return ExecutionResult(
                status=status,
                orders=[tracked.final_order],
                reason="" if status == "filled" else "close_failed",
            )
        execution = await self.executor.execute_pair(spot_leg, perp_leg)
        if execution.status == "failed" and not execution.reason:
            execution.reason = "close_failed"
        return execution

    def _route(self, request: ClosePositionRequest, *, urgent: bool) -> RouteDecision:
        return self.router.route(
            preferred_exchange=request.preferred_exchange,
            fallback_exchange=request.fallback_exchange,
            exchange_available=request.exchange_available,
            urgent=urgent,
            maker_fee_rate=request.maker_fee_rate,
            taker_fee_rate=request.taker_fee_rate,
            spread_bps=request.spread_bps,
        )

    def _alerts(self, request: ClosePositionRequest) -> list[RiskAlert]:
        alerts: list[RiskAlert] = []
        if self.kill_switch.active:
            alerts.append(RiskAlert("high", "killswitch_active", request.symbol))
        if request.funding_rate is not None:
            alert = self.risk_checker.check_funding_reversal(
                symbol=request.symbol,
                current_rate=request.funding_rate,
                min_expected_rate=request.min_expected_rate,
            )
            if alert is not None:
                alerts.append(alert)
        if request.max_holding_period is not None:
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
        if len(execution.orders) <= index:
            return default
        order = execution.orders[index]
        return max(Decimal(str(order.quantity)) - Decimal(str(order.filled_quantity)), Decimal("0"))

    def _is_success(self, execution: ExecutionResult) -> bool:
        return execution.status in {"filled", "adjusted"}
