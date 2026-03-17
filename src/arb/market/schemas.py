"""Typed market snapshot and event models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from arb.models import FundingRate, MarketType, OrderBook, Ticker, utc_now
from arb.schemas.base import ArbFrozenModel, SerializableValue


class NormalizedWsEvent(ArbFrozenModel):
    kind: Literal["ws_event"] = "ws_event"
    exchange: str
    channel: str
    payload: dict[str, SerializableValue]
    received_at: datetime


class MarketSnapshot(ArbFrozenModel):
    ticker: Ticker
    orderbook: OrderBook | None = None
    funding: FundingRate | None = None
    liquidity_usd: Decimal | None = None
    top_ask_size: Decimal | None = None


def coerce_ticker(
    payload: Ticker | dict[str, object],
    *,
    default_exchange: str | None = None,
    default_symbol: str | None = None,
    default_market_type: MarketType = MarketType.PERPETUAL,
    default_ts: datetime | None = None,
) -> Ticker:
    if isinstance(payload, Ticker):
        return payload
    data = dict(payload)
    data.pop("kind", None)
    data.setdefault("exchange", default_exchange or "")
    data.setdefault("symbol", default_symbol or "")
    data.setdefault("market_type", default_market_type.value)
    data.setdefault("last", data.get("ask", data.get("bid", "0")))
    data.setdefault("bid", data.get("last", "0"))
    data.setdefault("ask", data.get("last", data.get("bid", "0")))
    data.setdefault("ts", (default_ts or utc_now()).isoformat())
    return Ticker.model_validate(data)


def coerce_funding_rate(
    payload: FundingRate | dict[str, object],
    *,
    default_exchange: str | None = None,
    default_symbol: str | None = None,
    default_ts: datetime | None = None,
) -> FundingRate:
    if isinstance(payload, FundingRate):
        return payload
    data = dict(payload)
    data.pop("kind", None)
    timestamp = str(data.get("ts", (default_ts or utc_now()).isoformat()))
    data.setdefault("exchange", default_exchange or "")
    data.setdefault("symbol", default_symbol or "")
    data.setdefault("predicted_rate", data.get("rate"))
    data.setdefault("next_funding_time", timestamp)
    data.setdefault("ts", timestamp)
    return FundingRate.model_validate(data)


def coerce_market_snapshot(snapshot: MarketSnapshot | dict[str, object]) -> MarketSnapshot:
    if isinstance(snapshot, MarketSnapshot):
        return snapshot
    payload = dict(snapshot)
    funding_payload = payload.get("funding")
    funding = (
        coerce_funding_rate(funding_payload) if isinstance(funding_payload, dict) else funding_payload
    )
    ticker_payload = payload.get("ticker")
    if not isinstance(ticker_payload, dict):
        raise TypeError("snapshot.ticker must be a mapping or Ticker")
    ticker = coerce_ticker(
        ticker_payload,
        default_exchange=funding.exchange if isinstance(funding, FundingRate) else None,
        default_symbol=funding.symbol if isinstance(funding, FundingRate) else None,
        default_market_type=MarketType.PERPETUAL,
        default_ts=funding.ts if isinstance(funding, FundingRate) else None,
    )
    liquidity_value = payload.get("liquidity_usd")
    top_ask_size_value = payload.get("top_ask_size")
    return MarketSnapshot(
        ticker=ticker,
        funding=funding if isinstance(funding, FundingRate) else None,
        liquidity_usd=Decimal(str(liquidity_value)) if liquidity_value is not None else None,
        top_ask_size=Decimal(str(top_ask_size_value)) if top_ask_size_value is not None else None,
    )
