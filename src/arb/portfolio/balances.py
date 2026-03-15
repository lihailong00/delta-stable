"""Balance and margin helpers."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal


class BalanceBook:
    """Track balances and compute available margin."""

    def __init__(self) -> None:
        self._balances: dict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal("0"))
        self._reserved: dict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal("0"))

    def set_balance(self, exchange: str, asset: str, amount: Decimal) -> None:
        self._balances[(exchange, asset)] = amount

    def reserve(self, exchange: str, asset: str, amount: Decimal) -> None:
        self._reserved[(exchange, asset)] += amount

    def total_balance(self, exchange: str | None = None, asset: str | None = None) -> Decimal:
        total = Decimal("0")
        for (ex, ccy), amount in self._balances.items():
            if exchange is not None and ex != exchange:
                continue
            if asset is not None and ccy != asset:
                continue
            total += amount
        return total

    def available_margin(self, exchange: str, asset: str) -> Decimal:
        return self._balances[(exchange, asset)] - self._reserved[(exchange, asset)]
