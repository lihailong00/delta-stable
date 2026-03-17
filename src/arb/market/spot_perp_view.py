"""Spot/perpetual synchronized market view helpers."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import computed_field, model_validator

from arb.market.schemas import MarketSnapshot, coerce_funding_rate, coerce_ticker
from arb.models import FundingRate, MarketType, Ticker
from arb.schemas.base import ArbFrozenModel

def _parse_timestamp(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


class SpotPerpQuoteView(ArbFrozenModel):
    exchange: str
    symbol: str
    spot_ticker: Ticker
    perp_ticker: Ticker
    funding: FundingRate
    max_age_seconds: float = 3.0

    @model_validator(mode="before")
    @classmethod
    def _coerce_inputs(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        exchange = str(payload.get("exchange", ""))
        symbol = str(payload.get("symbol", ""))
        payload["spot_ticker"] = coerce_ticker(
            payload["spot_ticker"],
            default_exchange=exchange,
            default_symbol=symbol,
            default_market_type=MarketType.SPOT,
        )
        payload["perp_ticker"] = coerce_ticker(
            payload["perp_ticker"],
            default_exchange=exchange,
            default_symbol=symbol,
            default_market_type=MarketType.PERPETUAL,
        )
        payload["funding"] = coerce_funding_rate(
            payload["funding"],
            default_exchange=exchange,
            default_symbol=symbol,
        )
        return payload

    @computed_field(return_type=str)
    @property
    def kind(self) -> str:
        return "spot_perp_view"

    def basis_bps(self) -> Decimal:
        spot_ask = self.spot_ticker.ask
        perp_bid = self.perp_ticker.bid
        if spot_ask == 0:
            return Decimal("0")
        return ((perp_bid - spot_ask) / spot_ask) * Decimal("10000")

    @computed_field(alias="basis_bps", return_type=Decimal)
    @property
    def basis_bps_value(self) -> Decimal:
        return self.basis_bps()

    def synchronized_within(self, max_age_seconds: float) -> bool:
        spot_ts = _parse_timestamp(self.spot_ticker.ts)
        perp_ts = _parse_timestamp(self.perp_ticker.ts)
        return abs((perp_ts - spot_ts).total_seconds()) <= max_age_seconds

    @computed_field(alias="synchronized", return_type=bool)
    @property
    def synchronized_value(self) -> bool:
        return self.synchronized_within(self.max_age_seconds)


class SpotPerpSnapshot(ArbFrozenModel):
    spot: MarketSnapshot
    perp: MarketSnapshot
    view: SpotPerpQuoteView


def build_spot_perp_view(
    *,
    exchange: str,
    symbol: str,
    spot_ticker: Ticker | dict[str, object],
    perp_ticker: Ticker | dict[str, object],
    funding: FundingRate | dict[str, object],
    max_age_seconds: float = 3.0,
) -> SpotPerpQuoteView:
    return SpotPerpQuoteView(
        exchange=exchange,
        symbol=symbol,
        spot_ticker=coerce_ticker(
            spot_ticker,
            default_exchange=exchange,
            default_symbol=symbol,
            default_market_type=MarketType.SPOT,
        ),
        perp_ticker=coerce_ticker(
            perp_ticker,
            default_exchange=exchange,
            default_symbol=symbol,
            default_market_type=MarketType.PERPETUAL,
        ),
        funding=coerce_funding_rate(
            funding,
            default_exchange=exchange,
            default_symbol=symbol,
        ),
        max_age_seconds=max_age_seconds,
    )
