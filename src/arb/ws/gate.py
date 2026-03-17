"""Gate.io WebSocket adapter."""

from __future__ import annotations

import time
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from arb.utils.symbols import exchange_symbol, normalize_symbol
from arb.ws.base import BaseWebSocketClient, WsEvent


class GateWebSocketClient(BaseWebSocketClient):
    """Gate.io WS v4 adapter."""

    endpoint = "wss://api.gateio.ws/ws/v4/"

    def __init__(self, *, private: bool = False) -> None:
        super().__init__("gate", self.endpoint, heartbeat_interval=30)
        self.private = private

    def build_subscribe_message(
        self,
        channel: str,
        *,
        symbol: str | None = None,
        market: str | None = None,
    ) -> Mapping[str, Any]:
        if self.private and channel in {"spot.orders", "futures.orders", "futures.usertrades", "futures.positions"}:
            return {
                "time": int(time.time()),
                "channel": channel,
                "event": "subscribe",
                "payload": [exchange_symbol(symbol, delimiter="_")] if symbol is not None else [],
            }
        if symbol is None:
            raise ValueError("symbol is required for Gate subscriptions")
        if channel != "spot.order_book":
            raise ValueError(f"unsupported Gate channel: {channel}")
        return {
            "time": int(time.time()),
            "channel": channel,
            "event": "subscribe",
            "payload": [exchange_symbol(symbol, delimiter="_"), "20", "100ms"],
        }

    def build_ping_message(self) -> Mapping[str, Any]:
        return {"time": int(time.time()), "channel": "spot.ping"}

    def is_pong_message(self, message: Mapping[str, Any]) -> bool:
        return message.get("channel") == "spot.pong" or message.get("event") == "pong"

    def parse_message(self, message: Mapping[str, Any]) -> list[WsEvent]:
        if message.get("event") in {"subscribe", "unsubscribe"}:
            return []
        if message.get("channel") in {"spot.orders", "futures.orders"}:
            return self._parse_private_orders(message)
        if message.get("channel") == "futures.usertrades":
            return self._parse_private_fills(message)
        if message.get("channel") == "futures.positions":
            return self._parse_private_positions(message)
        if message.get("channel") != "spot.order_book":
            return []
        result = message.get("result", {})
        if not isinstance(result, Mapping):
            return []
        return [
            WsEvent(
                exchange=self.exchange,
                channel="orderbook.update",
                payload={
                    "symbol": normalize_symbol(str(result["s"])),
                    "bids": tuple(
                        (Decimal(str(level[0])), Decimal(str(level[1]))) for level in result.get("bids", [])
                    ),
                    "asks": tuple(
                        (Decimal(str(level[0])), Decimal(str(level[1]))) for level in result.get("asks", [])
                    ),
                    "timestamp": result.get("t"),
                },
            )
        ]

    def _parse_private_orders(self, message: Mapping[str, Any]) -> list[WsEvent]:
        items = message.get("result", [])
        if isinstance(items, Mapping):
            items = [items]
        events: list[WsEvent] = []
        for item in items:
            symbol = normalize_symbol(str(item.get("contract", item.get("currency_pair", ""))))
            events.append(
                WsEvent(
                    exchange=self.exchange,
                    channel="order.update",
                    payload={
                        "symbol": symbol,
                        "order_id": str(item.get("id", "")),
                        "side": str(item.get("side", "buy")).lower(),
                        "status": str(item.get("status", item.get("finish_as", "open"))).lower(),
                        "quantity": Decimal(str(item.get("amount", item.get("size", "0")))),
                        "filled_quantity": Decimal(str(item.get("filled_amount", item.get("fill_size", "0")))),
                        "price": Decimal(str(item["price"])) if item.get("price") not in (None, "", "0") else None,
                    },
                )
            )
        return events

    def _parse_private_fills(self, message: Mapping[str, Any]) -> list[WsEvent]:
        items = message.get("result", [])
        if isinstance(items, Mapping):
            items = [items]
        return [
            WsEvent(
                exchange=self.exchange,
                channel="fill.update",
                payload={
                    "symbol": normalize_symbol(str(item.get("contract", ""))),
                    "order_id": str(item.get("order_id", "")),
                    "fill_id": str(item.get("id", "")),
                    "side": ("buy" if Decimal(str(item.get("size", "0"))) > 0 else "sell"),
                    "quantity": abs(Decimal(str(item.get("size", "0")))),
                    "price": Decimal(str(item.get("price", "0"))),
                    "fee": Decimal(str(item.get("fee", "0"))),
                    "fee_asset": item.get("fee_currency"),
                },
            )
            for item in items
        ]

    def _parse_private_positions(self, message: Mapping[str, Any]) -> list[WsEvent]:
        items = message.get("result", [])
        if isinstance(items, Mapping):
            items = [items]
        return [
            WsEvent(
                exchange=self.exchange,
                channel="position.update",
                payload={
                    "symbol": normalize_symbol(str(item.get("contract", ""))),
                    "direction": "long" if Decimal(str(item.get("size", "0"))) > 0 else "short",
                    "quantity": abs(Decimal(str(item.get("size", "0")))),
                    "entry_price": Decimal(str(item.get("entry_price", "0"))),
                    "mark_price": Decimal(str(item.get("mark_price", "0"))),
                    "unrealized_pnl": Decimal(str(item.get("unrealised_pnl", "0"))),
                },
            )
            for item in items
            if Decimal(str(item.get("size", "0"))) != 0
        ]
