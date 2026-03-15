"""Portfolio position views."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from arb.models import Position, PositionDirection


class PositionBook:
    """Aggregate exchange-level positions and derive net exposure."""

    def __init__(self) -> None:
        self._positions: list[Position] = []

    def add(self, position: Position) -> None:
        self._positions.append(position)

    def all(self) -> list[Position]:
        return list(self._positions)

    def net_exposure_by_symbol(self) -> dict[str, Decimal]:
        exposures: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for position in self._positions:
            signed_quantity = position.quantity if position.direction is PositionDirection.LONG else -position.quantity
            exposures[position.symbol] += signed_quantity
        return dict(exposures)

    def hedge_ratio(self, symbol: str) -> Decimal:
        longs = Decimal("0")
        shorts = Decimal("0")
        for position in self._positions:
            if position.symbol != symbol:
                continue
            if position.direction is PositionDirection.LONG:
                longs += position.quantity
            else:
                shorts += position.quantity
        if longs == 0:
            return Decimal("0")
        return shorts / longs

    def is_balanced(self, symbol: str, *, tolerance: Decimal = Decimal("0.05")) -> bool:
        ratio = self.hedge_ratio(symbol)
        return abs(Decimal("1") - ratio) <= tolerance
