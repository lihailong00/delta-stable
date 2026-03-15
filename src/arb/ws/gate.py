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

    def __init__(self) -> None:
        super().__init__("gate", self.endpoint, heartbeat_interval=30)

    def build_subscribe_message(
        self,
        channel: str,
        *,
        symbol: str | None = None,
        market: str | None = None,
    ) -> Mapping[str, Any]:
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
