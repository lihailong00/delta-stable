"""PnL ledger."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass(slots=True, frozen=True)
class PnLEntry:
    ts: datetime
    category: str
    amount: Decimal
    strategy: str
    symbol: str


class PnLLedger:
    """Track PnL components for attribution."""

    def __init__(self) -> None:
        self._entries: list[PnLEntry] = []

    def add_entry(
        self,
        *,
        category: str,
        amount: Decimal,
        strategy: str,
        symbol: str,
        ts: datetime | None = None,
    ) -> None:
        self._entries.append(
            PnLEntry(ts=ts or utc_now(), category=category, amount=amount, strategy=strategy, symbol=symbol)
        )

    def entries(self) -> list[PnLEntry]:
        return list(self._entries)

    def summarize(self) -> dict[str, Decimal]:
        summary: dict[str, Decimal] = {}
        for entry in self._entries:
            summary[entry.category] = summary.get(entry.category, Decimal("0")) + entry.amount
        summary["total"] = sum((entry.amount for entry in self._entries), Decimal("0"))
        return summary
