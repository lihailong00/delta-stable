"""Execution routing helpers."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(slots=True, frozen=True)
class RouteDecision:
    mode: str
    exchange: str


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
        )
