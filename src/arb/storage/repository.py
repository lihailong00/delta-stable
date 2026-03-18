"""Persistence repository."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal

from arb.models import Fill, FundingRate, Order, Position, Ticker
from arb.schemas.base import SerializableValue
from arb.storage.db import Database
from arb.storage.schemas import (
    StoredFillRow,
    StoredFundingSnapshotRow,
    StoredOrderRow,
    StoredOrderStatusRow,
    StoredPositionRow,
    StoredWorkflowStateRow,
)


def _to_iso(value: datetime) -> str:
    return value.isoformat()


class Repository:
    """Repository for orders, fills, positions, funding snapshots and ticks."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def save_order(self, order: Order) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO orders (
                    order_id, exchange, symbol, market_type, side, quantity, price,
                    status, client_order_id, filled_quantity, average_price,
                    reduce_only, raw_status, ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order.order_id,
                    order.exchange,
                    order.symbol,
                    order.market_type.value,
                    order.side.value,
                    str(order.quantity),
                    str(order.price) if order.price is not None else None,
                    order.status.value,
                    order.client_order_id,
                    str(order.filled_quantity),
                    str(order.average_price) if order.average_price is not None else None,
                    int(order.reduce_only),
                    order.raw_status,
                    _to_iso(order.ts),
                ),
            )
        self.save_order_status(order)

    def save_position(self, position: Position) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO positions (
                    exchange, symbol, market_type, direction, quantity,
                    entry_price, mark_price, unrealized_pnl, liquidation_price,
                    leverage, margin_mode, position_id, ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    position.exchange,
                    position.symbol,
                    position.market_type.value,
                    position.direction.value,
                    str(position.quantity),
                    str(position.entry_price),
                    str(position.mark_price),
                    str(position.unrealized_pnl),
                    str(position.liquidation_price) if position.liquidation_price is not None else None,
                    str(position.leverage) if position.leverage is not None else None,
                    position.margin_mode,
                    position.position_id,
                    _to_iso(position.ts),
                ),
            )

    def save_funding(self, funding: FundingRate) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO funding_snapshots (
                    exchange, symbol, rate, predicted_rate, next_funding_time, ts
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    funding.exchange,
                    funding.symbol,
                    str(funding.rate),
                    str(funding.predicted_rate) if funding.predicted_rate is not None else None,
                    _to_iso(funding.next_funding_time),
                    _to_iso(funding.ts),
                ),
            )

    def save_ticker(self, ticker: Ticker) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO ticks (
                    exchange, symbol, market_type, bid, ask, last, ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticker.exchange,
                    ticker.symbol,
                    ticker.market_type.value,
                    str(ticker.bid),
                    str(ticker.ask),
                    str(ticker.last),
                    _to_iso(ticker.ts),
                ),
            )

    def save_fill(self, fill: Fill | StoredFillRow) -> None:
        if isinstance(fill, Fill):
            fill_id = fill.fill_id
            order_id = fill.order_id
            exchange = fill.exchange
            symbol = fill.symbol
            market_type = fill.market_type.value
            side = fill.side.value
            quantity = str(fill.quantity)
            price = str(fill.price)
            fee: str | None = str(fill.fee)
            fee_asset = fill.fee_asset
            ts = _to_iso(fill.ts)
        else:
            fill_id = fill.fill_id
            order_id = fill.order_id
            exchange = fill.exchange
            symbol = fill.symbol
            market_type = fill.market_type
            side = fill.side
            quantity = fill.quantity
            price = fill.price
            fee = fill.fee
            fee_asset = fill.fee_asset
            ts = fill.ts
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO fills (
                    fill_id, order_id, exchange, symbol, market_type, side,
                    quantity, price, fee, fee_asset, ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fill_id,
                    order_id,
                    exchange,
                    symbol,
                    market_type,
                    side,
                    quantity,
                    price,
                    fee,
                    fee_asset,
                    ts,
                ),
            )

    def save_workflow_state(
        self,
        *,
        workflow_id: str,
        workflow_type: str,
        exchange: str,
        symbol: str,
        status: str,
        payload: Mapping[str, SerializableValue] | None = None,
        updated_at: datetime | None = None,
    ) -> None:
        self.save_workflow_state_record(
            StoredWorkflowStateRow(
                workflow_id=workflow_id,
                workflow_type=workflow_type,
                exchange=exchange,
                symbol=symbol,
                status=status,
                    payload={key: value for key, value in (payload or {}).items()},
                    updated_at=_to_iso(updated_at or datetime.now(tz=timezone.utc)),
                )
            )

    def save_workflow_state_record(self, record: StoredWorkflowStateRow) -> None:
        body = json.dumps(record.payload, sort_keys=True, default=str)
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO workflow_state (
                    workflow_id, workflow_type, exchange, symbol, status, payload, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.workflow_id,
                    record.workflow_type,
                    record.exchange,
                    record.symbol,
                    record.status,
                    body,
                    record.updated_at,
                ),
            )

    def save_order_status(self, order: Order) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO order_status_history (
                    order_id, exchange, symbol, market_type, status, filled_quantity, ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order.order_id,
                    order.exchange,
                    order.symbol,
                    order.market_type.value,
                    order.status.value,
                    str(order.filled_quantity),
                    _to_iso(order.ts),
                ),
            )

    def list_orders(self) -> list[StoredOrderRow]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT * FROM orders ORDER BY ts DESC").fetchall()
        return [StoredOrderRow.model_validate(dict(row)) for row in rows]

    def list_positions(self) -> list[StoredPositionRow]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT * FROM positions ORDER BY ts DESC").fetchall()
        return [StoredPositionRow.model_validate(dict(row)) for row in rows]

    def list_fills(self, *, order_id: str | None = None) -> list[StoredFillRow]:
        query = "SELECT * FROM fills"
        params: list[str] = []
        if order_id is not None:
            query += " WHERE order_id = ?"
            params.append(order_id)
        query += " ORDER BY ts DESC"
        with self.database.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [StoredFillRow.model_validate(dict(row)) for row in rows]

    def list_funding_history(
        self,
        *,
        exchange: str | None = None,
        symbol: str | None = None,
        limit: int = 100,
    ) -> list[StoredFundingSnapshotRow]:
        query = "SELECT * FROM funding_snapshots"
        clauses: list[str] = []
        params: list[str | int] = []
        if exchange is not None:
            clauses.append("exchange = ?")
            params.append(exchange)
        if symbol is not None:
            clauses.append("symbol = ?")
            params.append(symbol)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY ts DESC LIMIT ?"
        params.append(limit)
        with self.database.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [StoredFundingSnapshotRow.model_validate(dict(row)) for row in rows]

    def list_workflow_states(
        self,
        *,
        statuses: tuple[str, ...] | None = None,
    ) -> list[StoredWorkflowStateRow]:
        query = "SELECT * FROM workflow_state"
        params: list[str] = []
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            query += f" WHERE status IN ({placeholders})"
            params.extend(statuses)
        query += " ORDER BY updated_at DESC"
        with self.database.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        workflows = [dict(row) for row in rows]
        for workflow in workflows:
            workflow["payload"] = json.loads(workflow["payload"])
        return [StoredWorkflowStateRow.model_validate(workflow) for workflow in workflows]

    def list_order_status_history(self, order_id: str) -> list[StoredOrderStatusRow]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM order_status_history
                WHERE order_id = ?
                ORDER BY ts DESC
                """,
                (order_id,),
            ).fetchall()
        return [StoredOrderStatusRow.model_validate(dict(row)) for row in rows]

    def to_decimal(self, value: str | None) -> Decimal | None:
        if value is None:
            return None
        return Decimal(value)
