"""WebSocket boundary schemas."""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field

from arb.schemas.base import ArbFrozenModel, SerializableValue

type WsWireMessage = ArbFrozenModel | dict[str, SerializableValue] | str


class MethodSubscribeMessage(ArbFrozenModel):
    method: str
    params: list[SerializableValue]
    id: int


class OpArgsMessage(ArbFrozenModel):
    op: str
    args: list[SerializableValue]


class GateMessage(ArbFrozenModel):
    time: int
    channel: str
    event: str
    payload: list[SerializableValue] = Field(default_factory=list)


class HtxSubscribeMessage(ArbFrozenModel):
    sub: str
    id: str


class HtxActionMessage(ArbFrozenModel):
    action: str
    ch: str
    params: dict[str, SerializableValue] | None = None
    data: dict[str, SerializableValue] | None = None


class TickerUpdatePayload(ArbFrozenModel):
    symbol: str
    bid: Decimal
    ask: Decimal
    last: Decimal
    funding_rate: Decimal | None = None


class OrderBookTickerPayload(ArbFrozenModel):
    symbol: str
    best_bid: Decimal
    bid_qty: Decimal
    best_ask: Decimal
    ask_qty: Decimal


class OrderBookUpdatePayload(ArbFrozenModel):
    symbol: str
    bids: tuple[tuple[Decimal, Decimal], ...]
    asks: tuple[tuple[Decimal, Decimal], ...]
    first_update_id: int | None = None
    final_update_id: int | None = None
    update_id: int | None = None
    ts: int | str | None = None
    timestamp: int | None = None
    action: str | None = None
    type: str | None = None


class FundingUpdatePayload(ArbFrozenModel):
    symbol: str
    funding_rate: Decimal
    next_funding_time: int | str | None = None
    next_funding_rate: Decimal | None = None
    mark_price: Decimal | None = None
    index_price: Decimal | None = None


class OrderUpdatePayload(ArbFrozenModel):
    symbol: str
    order_id: str
    side: str
    status: str
    quantity: Decimal
    filled_quantity: Decimal
    price: Decimal | None = None


class FillUpdatePayload(ArbFrozenModel):
    symbol: str
    order_id: str
    fill_id: str
    side: str
    quantity: Decimal
    price: Decimal
    fee: Decimal
    fee_asset: str | None = None


class PositionUpdatePayload(ArbFrozenModel):
    symbol: str
    direction: str
    quantity: Decimal
    entry_price: Decimal
    mark_price: Decimal
    unrealized_pnl: Decimal


type WsEventPayload = (
    TickerUpdatePayload
    | OrderBookTickerPayload
    | OrderBookUpdatePayload
    | FundingUpdatePayload
    | OrderUpdatePayload
    | FillUpdatePayload
    | PositionUpdatePayload
    | dict[str, SerializableValue]
)
