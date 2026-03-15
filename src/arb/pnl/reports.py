"""PnL report builders."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from arb.pnl.ledger import PnLEntry


def build_daily_report(entries: list[PnLEntry]) -> list[dict[str, Any]]:
    grouped: dict[date, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: Decimal("0")))
    for entry in entries:
        bucket = grouped[entry.ts.date()]
        bucket[entry.category] += entry.amount
        bucket["total"] += entry.amount

    report: list[dict[str, Any]] = []
    for day in sorted(grouped):
        payload: dict[str, Any] = {"date": day.isoformat()}
        payload.update({key: str(value) for key, value in grouped[day].items()})
        report.append(payload)
    return report
