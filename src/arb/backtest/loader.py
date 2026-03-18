"""Historical data loading."""

from __future__ import annotations

from collections.abc import Mapping

from arb.backtest.schemas import HistoricalPoint, MergedBacktestRow
from arb.funding import DEFAULT_FUNDING_INTERVAL_HOURS
from arb.schemas.base import SerializableValue


def load_points(
    rows: list[MergedBacktestRow | Mapping[str, SerializableValue]],
) -> list[HistoricalPoint]:
    points: list[HistoricalPoint] = []
    for row in rows:
        if isinstance(row, MergedBacktestRow):
            points.append(
                HistoricalPoint(
                    ts=row.ts,
                    price=row.price,
                    funding_rate=row.funding_rate,
                    funding_interval_hours=row.funding_interval_hours,
                    liquidity_usd=row.liquidity_usd,
                )
            )
            continue
        points.append(
            HistoricalPoint.model_validate(
                {
                    "ts": row["ts"],
                    "price": row["price"],
                    "funding_rate": row["funding_rate"],
                    "funding_interval_hours": row.get(
                        "funding_interval_hours",
                        DEFAULT_FUNDING_INTERVAL_HOURS,
                    ),
                    "liquidity_usd": row.get("liquidity_usd", "0"),
                }
            )
        )
    return points
