"""Orderbook depth estimation helpers for capacity-aware scanning."""

from __future__ import annotations

from decimal import Decimal

from arb.models import OrderBook, Side
from arb.schemas.base import ArbFrozenModel

_BPS_SCALE = Decimal("10000")


class DepthFillEstimate(ArbFrozenModel):
    side: Side
    quantity: Decimal = Decimal("0")
    notional: Decimal = Decimal("0")
    vwap: Decimal | None = None
    slippage_bps: Decimal = Decimal("0")
    levels_used: int = 0


def estimate_fill_for_quantity(
    orderbook: OrderBook,
    *,
    side: Side | str,
    quantity: Decimal,
    max_levels: int | None = None,
) -> DepthFillEstimate:
    """Estimate fill quality for a target quantity using the visible book."""

    normalized_side = _normalize_side(side)
    if quantity <= 0:
        return DepthFillEstimate(side=normalized_side)
    levels = _levels(orderbook, normalized_side, max_levels=max_levels)
    if not levels:
        return DepthFillEstimate(side=normalized_side)

    total_quantity = Decimal("0")
    total_notional = Decimal("0")
    remaining = quantity
    levels_used = 0
    for level in levels:
        if remaining <= 0:
            break
        take = min(level.size, remaining)
        if take <= 0:
            continue
        total_quantity += take
        total_notional += level.price * take
        remaining -= take
        levels_used += 1

    if total_quantity <= 0:
        return DepthFillEstimate(side=normalized_side)
    vwap = total_notional / total_quantity
    return DepthFillEstimate(
        side=normalized_side,
        quantity=total_quantity,
        notional=total_notional,
        vwap=vwap,
        slippage_bps=_slippage_bps(best_price=levels[0].price, vwap=vwap, side=normalized_side),
        levels_used=levels_used,
    )


def estimate_max_fill_for_slippage(
    orderbook: OrderBook,
    *,
    side: Side | str,
    max_slippage_bps: Decimal = Decimal("0"),
    max_levels: int | None = None,
) -> DepthFillEstimate:
    """Estimate the maximum fill size that still respects a VWAP slippage budget."""

    normalized_side = _normalize_side(side)
    levels = _levels(orderbook, normalized_side, max_levels=max_levels)
    if not levels:
        return DepthFillEstimate(side=normalized_side)

    total_quantity = Decimal("0")
    total_notional = Decimal("0")
    levels_used = 0
    best_price = levels[0].price
    slippage = max(max_slippage_bps, Decimal("0")) / _BPS_SCALE
    limit_price = best_price * (Decimal("1") + slippage) if normalized_side is Side.BUY else best_price * (
        Decimal("1") - slippage
    )

    for level in levels:
        take = _allowed_size(
            side=normalized_side,
            total_quantity=total_quantity,
            total_notional=total_notional,
            level_price=level.price,
            level_size=level.size,
            limit_price=limit_price,
        )
        if take <= 0:
            break
        total_quantity += take
        total_notional += level.price * take
        levels_used += 1
        if take < level.size:
            break

    if total_quantity <= 0:
        return DepthFillEstimate(side=normalized_side)
    vwap = total_notional / total_quantity
    return DepthFillEstimate(
        side=normalized_side,
        quantity=total_quantity,
        notional=total_notional,
        vwap=vwap,
        slippage_bps=_slippage_bps(best_price=best_price, vwap=vwap, side=normalized_side),
        levels_used=levels_used,
    )


def _normalize_side(side: Side | str) -> Side:
    return side if isinstance(side, Side) else Side(str(side).lower())


def _levels(orderbook: OrderBook, side: Side, *, max_levels: int | None) -> tuple[object, ...]:
    levels = orderbook.asks if side is Side.BUY else orderbook.bids
    if max_levels is None or max_levels <= 0:
        return levels
    return levels[:max_levels]


def _allowed_size(
    *,
    side: Side,
    total_quantity: Decimal,
    total_notional: Decimal,
    level_price: Decimal,
    level_size: Decimal,
    limit_price: Decimal,
) -> Decimal:
    if level_size <= 0:
        return Decimal("0")
    if side is Side.BUY:
        if level_price <= limit_price:
            return level_size
        numerator = (limit_price * total_quantity) - total_notional
        if numerator <= 0:
            return Decimal("0")
        return min(level_size, numerator / (level_price - limit_price))
    if level_price >= limit_price:
        return level_size
    numerator = total_notional - (limit_price * total_quantity)
    if numerator <= 0:
        return Decimal("0")
    return min(level_size, numerator / (limit_price - level_price))


def _slippage_bps(*, best_price: Decimal, vwap: Decimal, side: Side) -> Decimal:
    if best_price <= 0:
        return Decimal("0")
    if side is Side.BUY:
        return ((vwap - best_price) / best_price) * _BPS_SCALE
    return ((best_price - vwap) / best_price) * _BPS_SCALE
