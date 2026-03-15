"""Persistence repository."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

from arb.models import FundingRate, Order, Position, Ticker
from arb.storage.db import Database


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
                    status, filled_quantity, average_price, ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    str(order.filled_quantity),
                    str(order.average_price) if order.average_price is not None else None,
                    _to_iso(order.ts),
                ),
            )

    def save_position(self, position: Position) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO positions (
                    exchange, symbol, market_type, direction, quantity,
                    entry_price, mark_price, unrealized_pnl, ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    def save_fill(self, fill: Mapping[str, Any]) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO fills (
                    fill_id, order_id, exchange, symbol, side, quantity, price, ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(fill["fill_id"]),
                    str(fill["order_id"]),
                    str(fill["exchange"]),
                    str(fill["symbol"]),
                    str(fill["side"]),
                    str(fill["quantity"]),
                    str(fill["price"]),
                    str(fill["ts"]),
                ),
            )

    def list_orders(self) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT * FROM orders ORDER BY ts DESC").fetchall()
        return [dict(row) for row in rows]

    def list_positions(self) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT * FROM positions ORDER BY ts DESC").fetchall()
        return [dict(row) for row in rows]

    def list_funding_history(
        self,
        *,
        exchange: str | None = None,
        symbol: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM funding_snapshots"
        clauses: list[str] = []
        params: list[Any] = []
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
        return [dict(row) for row in rows]

    def to_decimal(self, value: str | None) -> Decimal | None:
        if value is None:
            return None
        return Decimal(value)
