"""Pre-trade validation guards."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


class GuardViolation(Exception):
    """Raised when a trade leg fails validation."""


@dataclass(slots=True, frozen=True)
class GuardContext:
    available_balance: Decimal
    max_notional: Decimal
    supported_symbols: set[str]


class PreTradeGuards:
    """Validate order intent before execution."""

    def validate(
        self,
        *,
        symbol: str,
        quantity: Decimal,
        price: Decimal,
        context: GuardContext,
    ) -> None:
        if symbol not in context.supported_symbols:
            raise GuardViolation(f"unsupported symbol: {symbol}")
        notional = quantity * price
        if notional > context.max_notional:
            raise GuardViolation("notional exceeds configured limit")
        if notional > context.available_balance:
            raise GuardViolation("insufficient balance")
