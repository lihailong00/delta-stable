"""Shared domain models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


class MarketType(StrEnum):
    SPOT = "spot"
    PERPETUAL = "perpetual"


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(StrEnum):
    NEW = "new"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"


class PositionDirection(StrEnum):
    LONG = "long"
    SHORT = "short"


@dataclass(slots=True, frozen=True)
class Ticker:
    exchange: str
    symbol: str
    market_type: MarketType
    bid: Decimal
    ask: Decimal
    last: Decimal
    ts: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class OrderBookLevel:
    price: Decimal
    size: Decimal

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class OrderBook:
    exchange: str
    symbol: str
    market_type: MarketType
    bids: tuple[OrderBookLevel, ...]
    asks: tuple[OrderBookLevel, ...]
    ts: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class FundingRate:
    exchange: str
    symbol: str
    rate: Decimal
    next_funding_time: datetime
    predicted_rate: Decimal | None = None
    ts: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class Order:
    exchange: str
    symbol: str
    market_type: MarketType
    side: Side
    quantity: Decimal
    price: Decimal | None
    status: OrderStatus
    order_id: str | None = None
    filled_quantity: Decimal = Decimal("0")
    average_price: Decimal | None = None
    ts: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class Position:
    exchange: str
    symbol: str
    market_type: MarketType
    direction: PositionDirection
    quantity: Decimal
    entry_price: Decimal
    mark_price: Decimal
    unrealized_pnl: Decimal = Decimal("0")
    ts: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
