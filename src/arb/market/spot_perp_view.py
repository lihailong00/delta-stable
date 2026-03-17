"""Spot/perpetual synchronized market view helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


def _parse_timestamp(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


@dataclass(slots=True, frozen=True)
class SpotPerpQuoteView:
    exchange: str
    symbol: str
    spot_ticker: dict[str, Any]
    perp_ticker: dict[str, Any]
    funding: dict[str, Any]

    def basis_bps(self) -> Decimal:
        spot_ask = Decimal(str(self.spot_ticker["ask"]))
        perp_bid = Decimal(str(self.perp_ticker["bid"]))
        if spot_ask == 0:
            return Decimal("0")
        return ((perp_bid - spot_ask) / spot_ask) * Decimal("10000")

    def synchronized_within(self, max_age_seconds: float) -> bool:
        spot_ts = _parse_timestamp(self.spot_ticker["ts"])
        perp_ts = _parse_timestamp(self.perp_ticker["ts"])
        return abs((perp_ts - spot_ts).total_seconds()) <= max_age_seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "spot_perp_view",
            "exchange": self.exchange,
            "symbol": self.symbol,
            "basis_bps": format(self.basis_bps(), "f"),
            "spot_ticker": dict(self.spot_ticker),
            "perp_ticker": dict(self.perp_ticker),
            "funding": dict(self.funding),
        }


def build_spot_perp_view(
    *,
    exchange: str,
    symbol: str,
    spot_ticker: dict[str, Any],
    perp_ticker: dict[str, Any],
    funding: dict[str, Any],
    max_age_seconds: float = 3.0,
) -> dict[str, Any]:
    view = SpotPerpQuoteView(
        exchange=exchange,
        symbol=symbol,
        spot_ticker=spot_ticker,
        perp_ticker=perp_ticker,
        funding=funding,
    )
    payload = view.to_dict()
    payload["synchronized"] = view.synchronized_within(max_age_seconds)
    payload["max_age_seconds"] = max_age_seconds
    return payload
