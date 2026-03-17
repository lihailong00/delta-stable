"""Spot long / perpetual short funding strategy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from arb.funding import DEFAULT_FUNDING_INTERVAL_HOURS
from arb.scanner.cost_model import normalize_rate
from arb.strategy.engine import StrategyAction, StrategyDecision, StrategyState


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass(slots=True, frozen=True)
class SpotPerpInputs:
    symbol: str
    funding_rate: Decimal
    spot_price: Decimal
    perp_price: Decimal
    funding_interval_hours: int = DEFAULT_FUNDING_INTERVAL_HOURS
    spot_quantity: Decimal = Decimal("0")
    perp_quantity: Decimal = Decimal("0")


@dataclass(slots=True, frozen=True)
class EntryQuoteCheck:
    accepted: bool
    reason: str
    basis_bps: Decimal
    normalized_funding_rate: Decimal = Decimal("0")


class SpotPerpStrategy:
    """Decision logic for same-exchange spot/perp funding capture."""

    def __init__(
        self,
        *,
        min_open_funding_rate: Decimal = Decimal("0.0005"),
        close_funding_rate: Decimal = Decimal("0"),
        threshold_interval_hours: int = DEFAULT_FUNDING_INTERVAL_HOURS,
        max_basis_bps: Decimal = Decimal("25"),
        rebalance_threshold: Decimal = Decimal("0.05"),
        max_holding_period: timedelta = timedelta(days=5),
    ) -> None:
        self.min_open_funding_rate = min_open_funding_rate
        self.close_funding_rate = close_funding_rate
        self.threshold_interval_hours = threshold_interval_hours
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

    def check_entry_quote(self, inputs: SpotPerpInputs) -> EntryQuoteCheck:
        basis = self.basis_bps(inputs.spot_price, inputs.perp_price)
        normalized_funding_rate = self.normalize_funding_rate(
            inputs.funding_rate,
            interval_hours=inputs.funding_interval_hours,
        )
        if normalized_funding_rate < self.min_open_funding_rate:
            return EntryQuoteCheck(False, "funding_below_threshold", basis, normalized_funding_rate)
        if abs(basis) > self.max_basis_bps:
            return EntryQuoteCheck(False, "basis_out_of_range", basis, normalized_funding_rate)
        return EntryQuoteCheck(True, "quote_accepted", basis, normalized_funding_rate)

    def normalize_funding_rate(
        self,
        funding_rate: Decimal,
        *,
        interval_hours: int,
    ) -> Decimal:
        return normalize_rate(
            funding_rate,
            from_interval_hours=interval_hours,
            to_interval_hours=self.threshold_interval_hours,
        )

    def evaluate(
        self,
        inputs: SpotPerpInputs,
        *,
        state: StrategyState | None = None,
        now: datetime | None = None,
    ) -> StrategyDecision:
        current_state = state or StrategyState()
        current_time = now or _utc_now()
        quote_check = self.check_entry_quote(inputs)
        basis = quote_check.basis_bps
        hedge_ratio = self.target_hedge_ratio(
            spot_quantity=inputs.spot_quantity or Decimal("1"),
            perp_quantity=inputs.perp_quantity or inputs.spot_quantity or Decimal("1"),
        )

        if not current_state.is_open:
            if quote_check.accepted:
                return StrategyDecision(
                    StrategyAction.OPEN,
                    reason=quote_check.reason,
                    target_hedge_ratio=Decimal("1"),
                    metadata={
                        "symbol": inputs.symbol,
                        "normalized_funding_rate": quote_check.normalized_funding_rate,
                        "threshold_interval_hours": self.threshold_interval_hours,
                    },
                )
            return StrategyDecision(
                StrategyAction.HOLD,
                reason=quote_check.reason,
                metadata={
                    "symbol": inputs.symbol,
                    "normalized_funding_rate": quote_check.normalized_funding_rate,
                    "threshold_interval_hours": self.threshold_interval_hours,
                },
            )

        normalized_funding_rate = self.normalize_funding_rate(
            inputs.funding_rate,
            interval_hours=inputs.funding_interval_hours,
        )
        if normalized_funding_rate <= self.close_funding_rate:
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
