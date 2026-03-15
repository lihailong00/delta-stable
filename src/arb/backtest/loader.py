"""Historical data loading."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(slots=True, frozen=True)
class HistoricalPoint:
    ts: datetime
    price: Decimal
    funding_rate: Decimal
    liquidity_usd: Decimal


def load_points(rows: list[dict[str, Any]]) -> list[HistoricalPoint]:
    return [
        HistoricalPoint(
            ts=datetime.fromisoformat(str(row["ts"])),
            price=Decimal(str(row["price"])),
            funding_rate=Decimal(str(row["funding_rate"])),
            liquidity_usd=Decimal(str(row.get("liquidity_usd", "0"))),
        )
        for row in rows
    ]
