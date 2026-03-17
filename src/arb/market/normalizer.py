"""Normalization helpers for market data payloads."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum

from arb.market.schemas import MarketSnapshot, NormalizedWsEvent
from arb.models import FundingRate, OrderBook, Ticker
from arb.schemas.base import SerializableValue
from arb.ws.base import WsEvent


def _stringify(value: SerializableValue) -> SerializableValue:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_stringify(item) for item in value]
    if isinstance(value, list):
        return [_stringify(item) for item in value]
    if isinstance(value, dict):
        return {key: _stringify(item) for key, item in value.items()}
    return value


def normalize_ticker(ticker: Ticker) -> Ticker:
    return ticker


def normalize_orderbook(orderbook: OrderBook) -> OrderBook:
    return orderbook


def normalize_funding(funding: FundingRate) -> FundingRate:
    return funding


def normalize_ws_event(event: WsEvent) -> NormalizedWsEvent:
    return NormalizedWsEvent(
        exchange=event.exchange,
        channel=event.channel,
        received_at=event.received_at,
        payload=dict(event.payload),
    )
