"""Risk limit checks."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(slots=True, frozen=True)
class RiskLimits:
    max_leverage: Decimal
    max_position_notional: Decimal

    def validate_leverage(self, leverage: Decimal) -> bool:
        return leverage <= self.max_leverage

    def validate_position_size(self, notional: Decimal) -> bool:
        return notional <= self.max_position_notional
