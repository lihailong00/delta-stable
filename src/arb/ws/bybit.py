"""Bybit WebSocket adapter."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from arb.models import MarketType
from arb.utils.symbols import exchange_symbol, normalize_symbol
from arb.ws.base import BaseWebSocketClient, WsEvent


class BybitWebSocketClient(BaseWebSocketClient):
    """Bybit public/private WS adapter."""

    public_template = "wss://stream.bybit.com/v5/public/{category}"
    private_endpoint = "wss://stream.bybit.com/v5/private"

    def __init__(
        self,
        market_type: MarketType = MarketType.SPOT,
        *,
        api_key: str | None = None,
        api_secret: str | None = None,
        private: bool = False,
    ) -> None:
        category = "spot" if market_type is MarketType.SPOT else "linear"
        endpoint = self.private_endpoint if private else self.public_template.format(category=category)
        super().__init__("bybit", endpoint, heartbeat_interval=20)
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
        if self.private and channel in {"order", "execution", "position"}:
            return {"op": "subscribe", "args": [channel]}
        if symbol is None:
            raise ValueError("symbol is required for Bybit subscriptions")
        topic_symbol = exchange_symbol(symbol, delimiter="")
        if channel == "orderbook":
            topic = f"orderbook.50.{topic_symbol}"
        elif channel == "ticker":
            topic = f"tickers.{topic_symbol}"
        else:
            raise ValueError(f"unsupported Bybit channel: {channel}")
        return {"op": "subscribe", "args": [topic]}

    def build_auth_message(self, expires: int) -> Mapping[str, Any]:
        if not self.api_key or not self.api_secret:
            raise ValueError("api_key and api_secret are required for auth")
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            f"GET/realtime{expires}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {"op": "auth", "args": [self.api_key, expires, signature]}

    def build_ping_message(self) -> Mapping[str, Any]:
        return {"op": "ping"}

    def is_pong_message(self, message: Mapping[str, Any]) -> bool:
        return message.get("op") == "pong" or message.get("ret_msg") == "pong"

    def parse_message(self, message: Mapping[str, Any]) -> list[WsEvent]:
        topic = message.get("topic")
        if not topic or message.get("success") is True:
            return []
        if topic == "order":
            return self._parse_private_orders(message)
        if topic == "execution":
            return self._parse_private_fills(message)
        if topic == "position":
            return self._parse_private_positions(message)
        if topic.startswith("orderbook."):
            return [self._parse_orderbook(message)]
        if topic.startswith("tickers."):
            return [self._parse_ticker(message)]
        return []

    def _parse_orderbook(self, message: Mapping[str, Any]) -> WsEvent:
        data = message["data"]
        return WsEvent(
            exchange=self.exchange,
            channel="orderbook.update",
            payload={
                "symbol": normalize_symbol(str(data["s"])),
                "type": message.get("type"),
                "bids": tuple((Decimal(str(price)), Decimal(str(size))) for price, size in data.get("b", [])),
                "asks": tuple((Decimal(str(price)), Decimal(str(size))) for price, size in data.get("a", [])),
                "update_id": data.get("u"),
            },
        )

    def _parse_ticker(self, message: Mapping[str, Any]) -> WsEvent:
        data = message["data"]
        return WsEvent(
            exchange=self.exchange,
            channel="ticker.update",
            payload={
                "symbol": normalize_symbol(str(data["symbol"])),
                "bid": Decimal(str(data["bid1Price"])),
                "ask": Decimal(str(data["ask1Price"])),
                "last": Decimal(str(data["lastPrice"])),
                "funding_rate": (
                    Decimal(str(data["fundingRate"]))
                    if data.get("fundingRate") is not None
                    else None
                ),
            },
        )

    def _parse_private_orders(self, message: Mapping[str, Any]) -> list[WsEvent]:
        events: list[WsEvent] = []
        for item in message.get("data", []):
            events.append(
                WsEvent(
                    exchange=self.exchange,
                    channel="order.update",
                    payload={
                        "symbol": normalize_symbol(str(item["symbol"])),
                        "order_id": str(item["orderId"]),
                        "side": str(item.get("side", "Buy")).lower(),
                        "status": str(item.get("orderStatus", "New")).lower(),
                        "quantity": Decimal(str(item.get("qty", "0"))),
                        "filled_quantity": Decimal(str(item.get("cumExecQty", "0"))),
                        "price": Decimal(str(item["price"])) if item.get("price") not in (None, "", "0") else None,
                    },
                )
            )
        return events

    def _parse_private_fills(self, message: Mapping[str, Any]) -> list[WsEvent]:
        events: list[WsEvent] = []
        for item in message.get("data", []):
            events.append(
                WsEvent(
                    exchange=self.exchange,
                    channel="fill.update",
                    payload={
                        "symbol": normalize_symbol(str(item["symbol"])),
                        "order_id": str(item["orderId"]),
                        "fill_id": str(item.get("execId", "")),
                        "side": str(item.get("side", "Buy")).lower(),
                        "quantity": Decimal(str(item.get("execQty", "0"))),
                        "price": Decimal(str(item.get("execPrice", "0"))),
                        "fee": Decimal(str(item.get("execFee", "0"))),
                        "fee_asset": item.get("feeCurrency"),
                    },
                )
            )
        return events

    def _parse_private_positions(self, message: Mapping[str, Any]) -> list[WsEvent]:
        events: list[WsEvent] = []
        for item in message.get("data", []):
            quantity = Decimal(str(item.get("size", "0")))
            if quantity == 0:
                continue
            events.append(
                WsEvent(
                    exchange=self.exchange,
                    channel="position.update",
                    payload={
                        "symbol": normalize_symbol(str(item["symbol"])),
                        "direction": str(item.get("side", "Buy")).lower(),
                        "quantity": quantity,
                        "entry_price": Decimal(str(item.get("avgPrice", "0"))),
                        "mark_price": Decimal(str(item.get("markPrice", "0"))),
                        "unrealized_pnl": Decimal(str(item.get("unrealisedPnl", item.get("unrealizedPnl", "0")))),
                    },
                )
            )
        return events
