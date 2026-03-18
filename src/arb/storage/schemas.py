"""Typed storage row schemas."""

from __future__ import annotations

from pydantic import ConfigDict, Field

from arb.schemas.base import ArbFrozenModel, SerializableValue


class StoredOrderRow(ArbFrozenModel):
    order_id: str | None = None
    exchange: str
    symbol: str
    market_type: str
    side: str
    quantity: str
    price: str | None = None
    status: str
    client_order_id: str | None = None
    filled_quantity: str
    average_price: str | None = None
    reduce_only: int = 0
    raw_status: str | None = None
    ts: str

    model_config = ConfigDict(extra="ignore", frozen=True)


class StoredPositionRow(ArbFrozenModel):
    exchange: str
    symbol: str
    market_type: str
    direction: str
    quantity: str
    entry_price: str
    mark_price: str
    unrealized_pnl: str
    liquidation_price: str | None = None
    leverage: str | None = None
    margin_mode: str | None = None
    position_id: str | None = None
    ts: str

    model_config = ConfigDict(extra="ignore", frozen=True)


class StoredFillRow(ArbFrozenModel):
    fill_id: str
    order_id: str
    exchange: str
    symbol: str
    market_type: str
    side: str
    quantity: str
    price: str
    fee: str | None = None
    fee_asset: str | None = None
    ts: str

    model_config = ConfigDict(extra="ignore", frozen=True)


class StoredFundingSnapshotRow(ArbFrozenModel):
    exchange: str
    symbol: str
    rate: str
    predicted_rate: str | None = None
    next_funding_time: str
    ts: str

    model_config = ConfigDict(extra="ignore", frozen=True)


class StoredOrderStatusRow(ArbFrozenModel):
    order_id: str | None = None
    exchange: str
    symbol: str
    market_type: str
    status: str
    filled_quantity: str
    ts: str

    model_config = ConfigDict(extra="ignore", frozen=True)


class StoredWorkflowStateRow(ArbFrozenModel):
    workflow_id: str
    workflow_type: str
    exchange: str
    symbol: str
    status: str
    payload: dict[str, SerializableValue] = Field(default_factory=dict)
    updated_at: str | None = None

    model_config = ConfigDict(extra="ignore", frozen=True)
