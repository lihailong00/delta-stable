"""Capital allocation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(slots=True, frozen=True)
class AllocationDecision:
    exchange: str
    symbol: str
    allocated_notional: Decimal
    constrained_by: str | None = None


class CapitalAllocator:
    """Allocate notional subject to per-symbol, per-exchange and portfolio limits."""

    def __init__(
        self,
        *,
        max_per_symbol: Decimal,
        max_per_exchange: Decimal,
        max_total: Decimal,
    ) -> None:
        self.max_per_symbol = max_per_symbol
        self.max_per_exchange = max_per_exchange
        self.max_total = max_total

    def allocate(
        self,
        *,
        exchange: str,
        symbol: str,
        requested_notional: Decimal,
        current_symbol_notional: Decimal = Decimal("0"),
        current_exchange_notional: Decimal = Decimal("0"),
        current_total_notional: Decimal = Decimal("0"),
    ) -> AllocationDecision:
        available_symbol = max(self.max_per_symbol - current_symbol_notional, Decimal("0"))
        available_exchange = max(self.max_per_exchange - current_exchange_notional, Decimal("0"))
        available_total = max(self.max_total - current_total_notional, Decimal("0"))

        limit = min(requested_notional, available_symbol, available_exchange, available_total)
        constrained_by = None
        if limit < requested_notional:
            if limit == available_symbol:
                constrained_by = "symbol_limit"
            elif limit == available_exchange:
                constrained_by = "exchange_limit"
            else:
                constrained_by = "portfolio_limit"

        return AllocationDecision(
            exchange=exchange,
            symbol=symbol,
            allocated_notional=limit,
            constrained_by=constrained_by,
        )
