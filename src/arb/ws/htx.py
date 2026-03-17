"""HTX WebSocket adapter."""

from __future__ import annotations

import time
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from arb.models import MarketType
from arb.utils.symbols import normalize_symbol, split_symbol
from arb.ws.base import BaseWebSocketClient, WsEvent


class HtxWebSocketClient(BaseWebSocketClient):
    """HTX public/private WS adapter."""

    public_endpoint = "wss://api.huobi.pro/ws"
    private_endpoint = "wss://api.huobi.pro/ws/v2"

    def __init__(
        self,
        market_type: MarketType = MarketType.SPOT,
        *,
        api_key: str | None = None,
        api_secret: str | None = None,
        private: bool = False,
    ) -> None:
        endpoint = self.private_endpoint if private else self.public_endpoint
        super().__init__("htx", endpoint, heartbeat_interval=30)
        self.market_type = market_type
        self.api_key = api_key
        self.api_secret = api_secret
        self.private = private

    def build_subscribe_message(
        self,
        channel: str,
        *,
        symbol: str | None = None,
        market: str | None = None,
    ) -> Mapping[str, Any]:
        if self.private and channel in {"orders", "positions"}:
            if symbol is None:
                return {"action": "sub", "ch": channel}
            suffix = self.to_exchange_symbol(symbol)
            return {"action": "sub", "ch": f"{channel}#{suffix}"}
        if symbol is None:
            raise ValueError("symbol is required for HTX subscriptions")
        if channel == "depth":
            suffix = "depth.step0"
        elif channel == "ticker":
            suffix = "detail.merged"
        else:
            raise ValueError(f"unsupported HTX channel: {channel}")
        return {"sub": f"market.{self.to_exchange_symbol(symbol)}.{suffix}", "id": str(int(time.time() * 1000))}

    def build_auth_message(self, params: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"action": "req", "ch": "auth", "params": dict(params)}

    def build_ping_message(self) -> Mapping[str, Any]:
        return {"action": "ping", "data": {"ts": int(time.time() * 1000)}}

    def is_pong_message(self, message: Mapping[str, Any]) -> bool:
        return "pong" in message or message.get("action") == "pong"

    def parse_message(self, message: Mapping[str, Any]) -> list[WsEvent]:
        if "ping" in message:
            return []
        if message.get("action") in {"req", "sub"} or message.get("status") == "ok":
            return []
        channel = str(message.get("ch", ""))
        if channel.startswith("orders#"):
            return self._parse_private_orders(message)
        if channel.startswith("positions"):
            return self._parse_private_positions(message)
        if channel.endswith(".depth.step0"):
            return [self._parse_depth(message)]
        if channel.endswith(".detail.merged"):
            return [self._parse_ticker(message)]
        return []

    def to_exchange_symbol(self, symbol: str) -> str:
        base, quote = split_symbol(symbol)
        if self.market_type is MarketType.PERPETUAL:
            return f"{base}-{quote}"
        return f"{base}{quote}".lower()

    def _parse_depth(self, message: Mapping[str, Any]) -> WsEvent:
        tick = message["tick"]
        channel = str(message["ch"])
        symbol = normalize_symbol(channel.split(".")[1])
        return WsEvent(
            exchange=self.exchange,
            channel="orderbook.update",
            payload={
                "symbol": symbol,
                "bids": tuple((Decimal(str(level[0])), Decimal(str(level[1]))) for level in tick.get("bids", [])),
                "asks": tuple((Decimal(str(level[0])), Decimal(str(level[1]))) for level in tick.get("asks", [])),
                "ts": tick.get("ts"),
            },
        )

    def _parse_ticker(self, message: Mapping[str, Any]) -> WsEvent:
        tick = message["tick"]
        channel = str(message["ch"])
        symbol = normalize_symbol(channel.split(".")[1])
        bid = tick["bid"][0] if isinstance(tick.get("bid"), list) else tick["close"]
        ask = tick["ask"][0] if isinstance(tick.get("ask"), list) else tick["close"]
        return WsEvent(
            exchange=self.exchange,
            channel="ticker.update",
            payload={
                "symbol": symbol,
                "bid": Decimal(str(bid)),
                "ask": Decimal(str(ask)),
                "last": Decimal(str(tick.get("close", bid))),
            },
        )

    def _parse_private_orders(self, message: Mapping[str, Any]) -> list[WsEvent]:
        data = message.get("data", {})
        items = data if isinstance(data, list) else [data]
        events: list[WsEvent] = []
        for item in items:
            events.append(
                WsEvent(
                    exchange=self.exchange,
                    channel="order.update",
                    payload={
                        "symbol": normalize_symbol(str(item.get("symbol", item.get("contract_code", "")))),
                        "order_id": str(item.get("order_id", item.get("orderId", ""))),
                        "side": str(item.get("order_side", item.get("direction", "buy"))).lower(),
                        "status": str(item.get("order_status", item.get("status", "submitted"))).lower(),
                        "quantity": Decimal(str(item.get("order_size", item.get("volume", "0")))),
                        "filled_quantity": Decimal(str(item.get("trade_volume", item.get("filled_amount", "0")))),
                        "price": Decimal(str(item["price"])) if item.get("price") not in (None, "", "0") else None,
                    },
                )
            )
        return events

    def _parse_private_positions(self, message: Mapping[str, Any]) -> list[WsEvent]:
        data = message.get("data", {})
        items = data if isinstance(data, list) else [data]
        events: list[WsEvent] = []
        for item in items:
            quantity = Decimal(str(item.get("volume", item.get("position", "0"))))
            if quantity == 0:
                continue
            events.append(
                WsEvent(
                    exchange=self.exchange,
                    channel="position.update",
                    payload={
                        "symbol": normalize_symbol(str(item.get("contract_code", item.get("symbol", "")))),
                        "direction": str(item.get("direction", "buy")).lower(),
                        "quantity": abs(quantity),
                        "entry_price": Decimal(str(item.get("cost_open", item.get("open_price_avg", "0")))),
                        "mark_price": Decimal(str(item.get("last_price", item.get("mark_price", "0")))),
                        "unrealized_pnl": Decimal(str(item.get("profit_unreal", "0"))),
                    },
                )
            )
        return events
