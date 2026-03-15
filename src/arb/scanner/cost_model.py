"""Cost model helpers for funding arbitrage."""

from __future__ import annotations

from decimal import Decimal


def estimate_net_rate(
    gross_rate: Decimal,
    *,
    trading_fee_rate: Decimal = Decimal("0"),
    slippage_rate: Decimal = Decimal("0"),
    borrow_rate: Decimal = Decimal("0"),
    transfer_rate: Decimal = Decimal("0"),
) -> Decimal:
    return gross_rate - trading_fee_rate - slippage_rate - borrow_rate - transfer_rate


def annualize_rate(rate: Decimal, *, periods_per_day: int = 3) -> Decimal:
    return rate * Decimal(periods_per_day) * Decimal(365)
