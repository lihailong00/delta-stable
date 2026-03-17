"""Execution routing helpers."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from arb.models import Side


@dataclass(slots=True, frozen=True)
class RouteDecision:
    mode: str
    exchange: str
    urgent: bool = False


class ExecutionRouter:
    """Choose maker/taker mode and preferred exchange for an order."""

    def choose_mode(
        self,
        *,
        urgent: bool,
        maker_fee_rate: Decimal,
        taker_fee_rate: Decimal,
        spread_bps: Decimal,
    ) -> str:
        if urgent or spread_bps <= Decimal("1"):
            return "taker"
        return "maker" if maker_fee_rate <= taker_fee_rate else "taker"

    def choose_exchange(
        self,
        *,
        preferred_exchange: str,
        fallback_exchange: str | None = None,
        exchange_available: bool = True,
    ) -> str:
        if exchange_available or fallback_exchange is None:
            return preferred_exchange
        return fallback_exchange

    def route(
        self,
        *,
        preferred_exchange: str,
        urgent: bool,
        maker_fee_rate: Decimal,
        taker_fee_rate: Decimal,
        spread_bps: Decimal,
        fallback_exchange: str | None = None,
        exchange_available: bool = True,
    ) -> RouteDecision:
        return RouteDecision(
            mode=self.choose_mode(
                urgent=urgent,
                maker_fee_rate=maker_fee_rate,
                taker_fee_rate=taker_fee_rate,
                spread_bps=spread_bps,
            ),
            exchange=self.choose_exchange(
                preferred_exchange=preferred_exchange,
                fallback_exchange=fallback_exchange,
                exchange_available=exchange_available,
            ),
            urgent=urgent,
        )

    def quote_price(
        self,
        *,
        reference_price: Decimal,
        side: str | Side,
        mode: str,
        max_slippage_bps: Decimal = Decimal("0"),
    ) -> Decimal:
        if mode == "maker" or max_slippage_bps <= 0:
            return reference_price
        multiplier = Decimal("1") + (max_slippage_bps / Decimal("10000"))
        normalized_side = Side(str(side).lower())
        if normalized_side is Side.BUY:
            return reference_price * multiplier
        return reference_price / multiplier

    def should_escalate_to_taker(
        self,
        *,
        current_mode: str,
        elapsed_seconds: float,
        max_naked_seconds: float,
    ) -> bool:
        return (
            current_mode != "taker"
            and max_naked_seconds > 0
            and elapsed_seconds >= max_naked_seconds
        )
