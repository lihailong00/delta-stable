"""Open-position workflow for spot long / perpetual short funding capture."""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from arb.funding import DEFAULT_FUNDING_INTERVAL_HOURS
from arb.execution.executor import ExecutionLeg, ExecutionResult, PairExecutor
from arb.execution.guards import GuardContext
from arb.execution.protocols import ClockFn, CreateOrderClient
from arb.execution.router import ExecutionRouter, RouteDecision
from arb.models import MarketType, Order, Side
from arb.strategy.spot_perp import SpotPerpInputs, SpotPerpStrategy


@dataclass(slots=True, frozen=True)
class VenueClients:
    exchange: str
    spot_client: CreateOrderClient
    perp_client: CreateOrderClient
    spot_context: GuardContext | None = None
    perp_context: GuardContext | None = None


@dataclass(slots=True, frozen=True)
class OpenPositionRequest:
    symbol: str
    quantity: Decimal
    funding_rate: Decimal
    spot_price: Decimal
    perp_price: Decimal
    venue_clients: Mapping[str, VenueClients]
    preferred_exchange: str
    funding_interval_hours: int = DEFAULT_FUNDING_INTERVAL_HOURS
    fallback_exchange: str | None = None
    exchange_available: bool = True
    maker_fee_rate: Decimal = Decimal("0")
    taker_fee_rate: Decimal = Decimal("0")
    spread_bps: Decimal = Decimal("5")
    max_slippage_bps: Decimal = Decimal("5")
    max_naked_seconds: float = 2.0
    allow_taker_fallback: bool = True


@dataclass(slots=True, frozen=True)
class CrossExchangeOpenRequest:
    symbol: str
    quantity: Decimal
    long_exchange: str
    short_exchange: str
    long_price: Decimal
    short_price: Decimal
    venue_clients: Mapping[str, VenueClients]
    maker_fee_rate: Decimal = Decimal("0")
    taker_fee_rate: Decimal = Decimal("0")
    spread_bps: Decimal = Decimal("5")
    max_slippage_bps: Decimal = Decimal("5")
    urgent: bool = False


@dataclass(slots=True)
class OpenPositionResult:
    status: str
    reason: str
    route: RouteDecision | None = None
    execution: ExecutionResult | None = None
    rollback_orders: list[Order] = field(default_factory=list)
    attempts: int = 0


class OpenPositionWorkflow:
    """Coordinate quote checks, routing, execution and rollback for entry."""

    def __init__(
        self,
        *,
        strategy: SpotPerpStrategy | None = None,
        executor: PairExecutor | None = None,
        router: ExecutionRouter | None = None,
        clock: ClockFn | None = None,
    ) -> None:
        self.strategy = strategy or SpotPerpStrategy()
        self.executor = executor or PairExecutor()
        self.router = router or ExecutionRouter()
        self.clock = clock or time.monotonic

    async def execute(self, request: OpenPositionRequest) -> OpenPositionResult:
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
            return OpenPositionResult(status="rejected", reason=quote_check.reason)

        started_at = float(self.clock())
        route = self._route(request, urgent=False)
        execution = await self._attempt(request, route)
        attempts = 1

        if self._is_success(execution):
            return OpenPositionResult(
                status="opened",
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
            retry_route = self._route(request, urgent=True)
            retry_execution = await self._attempt(request, retry_route)
            attempts += 1
            if self._is_success(retry_execution):
                return OpenPositionResult(
                    status="opened",
                    reason="opened_after_taker_fallback",
                    route=retry_route,
                    execution=retry_execution,
                    attempts=attempts,
                )
            execution = retry_execution
            route = retry_route
            elapsed = float(self.clock()) - started_at

        rollback_orders, rollback_reason = await self._maybe_rollback(
            request,
            route,
            execution,
            elapsed_seconds=elapsed,
        )
        status = "rolled_back" if rollback_orders else "failed"
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
        route = self.router.route(
            preferred_exchange=request.short_exchange,
            fallback_exchange=request.long_exchange,
            exchange_available=True,
            urgent=request.urgent,
            maker_fee_rate=request.maker_fee_rate,
            taker_fee_rate=request.taker_fee_rate,
            spread_bps=request.spread_bps,
        )
        long_venue = request.venue_clients.get(request.long_exchange)
        short_venue = request.venue_clients.get(request.short_exchange)
        if long_venue is None or short_venue is None:
            missing = request.long_exchange if long_venue is None else request.short_exchange
            return OpenPositionResult(status="failed", reason=f"missing venue: {missing}", route=route)

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
        if execution.status in {"filled", "adjusted"}:
            return OpenPositionResult(
                status="opened",
                reason="opened",
                route=route,
                execution=execution,
                attempts=1,
            )
        return OpenPositionResult(
            status="failed",
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
        venue = request.venue_clients.get(route.exchange)
        if venue is None:
            return ExecutionResult(status="failed", reason=f"missing venue: {route.exchange}")
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
        if execution.status == "failed" and not execution.reason:
            execution.reason = "open_failed"
        return execution

    def _route(self, request: OpenPositionRequest, *, urgent: bool) -> RouteDecision:
        return self.router.route(
            preferred_exchange=request.preferred_exchange,
            fallback_exchange=request.fallback_exchange,
            exchange_available=request.exchange_available,
            urgent=urgent,
            maker_fee_rate=request.maker_fee_rate,
            taker_fee_rate=request.taker_fee_rate,
            spread_bps=request.spread_bps,
        )

    def _can_retry_with_taker(
        self,
        request: OpenPositionRequest,
        route: RouteDecision,
        execution: ExecutionResult,
        elapsed_seconds: float,
    ) -> bool:
        if route.mode == "taker":
            return False
        if execution.status != "failed":
            return False
        if self._has_exposure(execution):
            return False
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
        if not self._has_exposure(execution):
            if self.router.should_escalate_to_taker(
                current_mode=route.mode,
                elapsed_seconds=elapsed_seconds,
                max_naked_seconds=request.max_naked_seconds,
            ):
                return [], "naked_time_exceeded"
            return [], execution.reason or None

        venue = request.venue_clients.get(route.exchange)
        if venue is None:
            return [], execution.reason or f"missing venue: {route.exchange}"

        rollback_orders: list[Order] = []
        for order in execution.orders:
            filled_quantity = Decimal(str(getattr(order, "filled_quantity", "0")))
            if filled_quantity <= 0:
                continue
            if order.market_type is MarketType.SPOT:
                client = venue.spot_client
                side = Side.SELL.value
                reduce_only = False
            else:
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
        reason = "naked_time_exceeded" if elapsed_seconds >= request.max_naked_seconds else "rollback_after_open_failure"
        return rollback_orders, reason

    def _has_exposure(self, execution: ExecutionResult) -> bool:
        return any(order.filled_quantity > 0 for order in execution.orders)

    def _is_success(self, execution: ExecutionResult) -> bool:
        return execution.status in {"filled", "adjusted"}
