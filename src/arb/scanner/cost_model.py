"""Cost model helpers for funding arbitrage."""

from __future__ import annotations

from decimal import Decimal

from arb.funding import DEFAULT_FUNDING_INTERVAL_HOURS


def estimate_net_rate(
    gross_rate: Decimal,
    *,
    trading_fee_rate: Decimal = Decimal("0"),
    slippage_rate: Decimal = Decimal("0"),
    borrow_rate: Decimal = Decimal("0"),
    transfer_rate: Decimal = Decimal("0"),
) -> Decimal:
    return gross_rate - trading_fee_rate - slippage_rate - borrow_rate - transfer_rate


def periods_per_day(interval_hours: int = DEFAULT_FUNDING_INTERVAL_HOURS) -> Decimal:
    return Decimal("24") / Decimal(interval_hours)


def hourly_rate(
    rate: Decimal,
    *,
    interval_hours: int = DEFAULT_FUNDING_INTERVAL_HOURS,
) -> Decimal:
    return rate / Decimal(interval_hours)


def daily_rate(
    rate: Decimal,
    *,
    interval_hours: int = DEFAULT_FUNDING_INTERVAL_HOURS,
) -> Decimal:
    return hourly_rate(rate, interval_hours=interval_hours) * Decimal("24")


def normalize_rate(
    rate: Decimal,
    *,
    from_interval_hours: int = DEFAULT_FUNDING_INTERVAL_HOURS,
    to_interval_hours: int = 1,
) -> Decimal:
    return hourly_rate(rate, interval_hours=from_interval_hours) * Decimal(to_interval_hours)


def annualize_rate(
    rate: Decimal,
    *,
    interval_hours: int = DEFAULT_FUNDING_INTERVAL_HOURS,
) -> Decimal:
    return daily_rate(rate, interval_hours=interval_hours) * Decimal("365")
