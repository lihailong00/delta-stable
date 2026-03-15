"""Spot long / perpetual short funding strategy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from arb.strategy.engine import StrategyAction, StrategyDecision, StrategyState


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass(slots=True, frozen=True)
class SpotPerpInputs:
    symbol: str
    funding_rate: Decimal
    spot_price: Decimal
    perp_price: Decimal
    spot_quantity: Decimal = Decimal("0")
    perp_quantity: Decimal = Decimal("0")


class SpotPerpStrategy:
    """Decision logic for same-exchange spot/perp funding capture."""

    def __init__(
        self,
        *,
        min_open_funding_rate: Decimal = Decimal("0.0005"),
        close_funding_rate: Decimal = Decimal("0"),
        max_basis_bps: Decimal = Decimal("25"),
        rebalance_threshold: Decimal = Decimal("0.05"),
        max_holding_period: timedelta = timedelta(days=5),
    ) -> None:
        self.min_open_funding_rate = min_open_funding_rate
        self.close_funding_rate = close_funding_rate
        self.max_basis_bps = max_basis_bps
        self.rebalance_threshold = rebalance_threshold
        self.max_holding_period = max_holding_period

    def basis_bps(self, spot_price: Decimal, perp_price: Decimal) -> Decimal:
        if spot_price == 0:
            return Decimal("0")
        return ((perp_price - spot_price) / spot_price) * Decimal("10000")

    def target_hedge_ratio(
        self,
        *,
        spot_quantity: Decimal,
        perp_quantity: Decimal,
    ) -> Decimal:
        if spot_quantity == 0:
            return Decimal("0")
        return perp_quantity / spot_quantity

    def evaluate(
        self,
        inputs: SpotPerpInputs,
        *,
        state: StrategyState | None = None,
        now: datetime | None = None,
    ) -> StrategyDecision:
        current_state = state or StrategyState()
        current_time = now or _utc_now()
        basis = self.basis_bps(inputs.spot_price, inputs.perp_price)
        hedge_ratio = self.target_hedge_ratio(
            spot_quantity=inputs.spot_quantity or Decimal("1"),
            perp_quantity=inputs.perp_quantity or inputs.spot_quantity or Decimal("1"),
        )

        if not current_state.is_open:
            if inputs.funding_rate >= self.min_open_funding_rate and abs(basis) <= self.max_basis_bps:
                return StrategyDecision(
                    StrategyAction.OPEN,
                    reason="funding_above_threshold",
                    target_hedge_ratio=Decimal("1"),
                    metadata={"symbol": inputs.symbol},
                )
            return StrategyDecision(StrategyAction.HOLD, reason="no_open_signal", metadata={"symbol": inputs.symbol})

        if inputs.funding_rate <= self.close_funding_rate:
            return StrategyDecision(StrategyAction.CLOSE, reason="funding_reversed", metadata={"symbol": inputs.symbol})

        if current_state.opened_at and current_time - current_state.opened_at > self.max_holding_period:
            return StrategyDecision(StrategyAction.CLOSE, reason="holding_period_exceeded", metadata={"symbol": inputs.symbol})

        if abs(Decimal("1") - hedge_ratio) > self.rebalance_threshold:
            return StrategyDecision(
                StrategyAction.REBALANCE,
                reason="hedge_ratio_drift",
                target_hedge_ratio=Decimal("1"),
                metadata={"symbol": inputs.symbol},
            )

        return StrategyDecision(StrategyAction.HOLD, reason="position_healthy", target_hedge_ratio=hedge_ratio, metadata={"symbol": inputs.symbol})
