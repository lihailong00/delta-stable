"""Cross-exchange perpetual spread strategy."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from arb.strategy.engine import StrategyAction, StrategyDecision, StrategyState


@dataclass(slots=True, frozen=True)
class PerpSpreadInputs:
    symbol: str
    long_exchange: str
    short_exchange: str
    long_funding_rate: Decimal
    short_funding_rate: Decimal
    long_price: Decimal
    short_price: Decimal
    long_quantity: Decimal = Decimal("0")
    short_quantity: Decimal = Decimal("0")


class PerpSpreadReason(StrEnum):
    SPREAD_ABOVE_THRESHOLD = "spread_above_threshold"
    NO_OPEN_SIGNAL = "no_open_signal"
    SPREAD_COMPRESSED = "spread_compressed"
    HEDGE_RATIO_DRIFT = "hedge_ratio_drift"
    SPREAD_HEALTHY = "spread_healthy"


class PerpSpreadStrategy:
    """Decision logic for cross-exchange perpetual funding spreads."""

    def __init__(
        self,
        *,
        min_spread_rate: Decimal = Decimal("0.0005"),
        close_spread_rate: Decimal = Decimal("0.0001"),
        rebalance_threshold: Decimal = Decimal("0.05"),
    ) -> None:
        self.min_spread_rate = min_spread_rate
        self.close_spread_rate = close_spread_rate
        self.rebalance_threshold = rebalance_threshold

    def spread_rate(self, inputs: PerpSpreadInputs) -> Decimal:
        return inputs.short_funding_rate - inputs.long_funding_rate

    def hedge_ratio(self, inputs: PerpSpreadInputs) -> Decimal:
        long_notional = inputs.long_price * inputs.long_quantity
        short_notional = inputs.short_price * inputs.short_quantity
        if long_notional == 0:
            return Decimal("0")
        return short_notional / long_notional

    def evaluate(
        self,
        inputs: PerpSpreadInputs,
        *,
        state: StrategyState | None = None,
    ) -> StrategyDecision:
        current_state = state or StrategyState()
        spread = self.spread_rate(inputs)
        hedge_ratio = self.hedge_ratio(inputs)

        if not current_state.is_open:
            if spread >= self.min_spread_rate:
                return StrategyDecision(
                    StrategyAction.OPEN,
                    reason=PerpSpreadReason.SPREAD_ABOVE_THRESHOLD,
                    target_hedge_ratio=Decimal("1"),
                    metadata={"symbol": inputs.symbol},
                )
            return StrategyDecision(StrategyAction.HOLD, reason=PerpSpreadReason.NO_OPEN_SIGNAL, metadata={"symbol": inputs.symbol})

        if spread <= self.close_spread_rate:
            return StrategyDecision(StrategyAction.CLOSE, reason=PerpSpreadReason.SPREAD_COMPRESSED, metadata={"symbol": inputs.symbol})

        if hedge_ratio and abs(Decimal("1") - hedge_ratio) > self.rebalance_threshold:
            return StrategyDecision(
                StrategyAction.REBALANCE,
                reason=PerpSpreadReason.HEDGE_RATIO_DRIFT,
                target_hedge_ratio=Decimal("1"),
                metadata={"symbol": inputs.symbol},
            )

        return StrategyDecision(StrategyAction.HOLD, reason=PerpSpreadReason.SPREAD_HEALTHY, target_hedge_ratio=hedge_ratio or Decimal("1"), metadata={"symbol": inputs.symbol})
