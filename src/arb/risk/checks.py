"""Risk check primitives."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(slots=True, frozen=True)
class RiskAlert:
    severity: str
    reason: str
    symbol: str


class RiskChecker:
    """Evaluate common funding arbitrage risk conditions."""

    def check_liquidation_buffer(
        self,
        *,
        symbol: str,
        mark_price: Decimal,
        liquidation_price: Decimal,
        min_buffer_bps: Decimal,
    ) -> RiskAlert | None:
        if mark_price == 0:
            return None
        buffer_bps = abs(mark_price - liquidation_price) / mark_price * Decimal("10000")
        if buffer_bps < min_buffer_bps:
            return RiskAlert("high", "liquidation_buffer_low", symbol)
        return None

    def check_basis(
        self,
        *,
        symbol: str,
        spot_price: Decimal,
        perp_price: Decimal,
        max_basis_bps: Decimal,
    ) -> RiskAlert | None:
        if spot_price == 0:
            return None
        basis_bps = abs(perp_price - spot_price) / spot_price * Decimal("10000")
        if basis_bps > max_basis_bps:
            return RiskAlert("medium", "basis_out_of_range", symbol)
        return None

    def check_funding_reversal(
        self,
        *,
        symbol: str,
        current_rate: Decimal,
        min_expected_rate: Decimal,
    ) -> RiskAlert | None:
        if current_rate < min_expected_rate:
            return RiskAlert("medium", "funding_reversal", symbol)
        return None

    def check_naked_leg(
        self,
        *,
        symbol: str,
        long_quantity: Decimal,
        short_quantity: Decimal,
        tolerance: Decimal = Decimal("0.02"),
    ) -> RiskAlert | None:
        if long_quantity == 0 and short_quantity == 0:
            return None
        baseline = max(long_quantity, short_quantity, Decimal("1"))
        imbalance = abs(long_quantity - short_quantity) / baseline
        if imbalance > tolerance:
            return RiskAlert("high", "naked_leg", symbol)
        return None
