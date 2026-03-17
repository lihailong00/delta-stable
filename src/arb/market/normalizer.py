"""Normalization helpers for market data payloads."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum

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


def normalize_ticker(ticker: Ticker) -> dict[str, SerializableValue]:
    payload = ticker.to_dict()
    payload["kind"] = "ticker"
    return _stringify(payload)


def normalize_orderbook(orderbook: OrderBook) -> dict[str, SerializableValue]:
    payload = orderbook.to_dict()
    payload["kind"] = "orderbook"
    return _stringify(payload)


def normalize_funding(funding: FundingRate) -> dict[str, SerializableValue]:
    payload = funding.to_dict()
    payload["kind"] = "funding"
    return _stringify(payload)


def normalize_ws_event(event: WsEvent) -> dict[str, SerializableValue]:
    payload = {
        "kind": "ws_event",
        "exchange": event.exchange,
        "channel": event.channel,
        "received_at": event.received_at,
        "payload": event.payload,
    }
    return _stringify(payload)
