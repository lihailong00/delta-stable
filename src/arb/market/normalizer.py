"""Normalization helpers for market data payloads."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import Any

from arb.models import FundingRate, OrderBook, Ticker
from arb.ws.base import WsEvent


def _stringify(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_stringify(item) for item in value]
    if isinstance(value, list):
        return [_stringify(item) for item in value]
    if isinstance(value, dict):
        return {key: _stringify(item) for key, item in value.items()}
    return value


def normalize_ticker(ticker: Ticker) -> dict[str, Any]:
    payload = asdict(ticker)
    payload["kind"] = "ticker"
    return _stringify(payload)


def normalize_orderbook(orderbook: OrderBook) -> dict[str, Any]:
    payload = asdict(orderbook)
    payload["kind"] = "orderbook"
    return _stringify(payload)


def normalize_funding(funding: FundingRate) -> dict[str, Any]:
    payload = asdict(funding)
    payload["kind"] = "funding"
    return _stringify(payload)


def normalize_ws_event(event: WsEvent) -> dict[str, Any]:
    payload = {
        "kind": "ws_event",
        "exchange": event.exchange,
        "channel": event.channel,
        "received_at": event.received_at,
        "payload": dict(event.payload),
    }
    return _stringify(payload)
