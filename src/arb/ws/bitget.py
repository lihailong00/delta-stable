"""Bitget WebSocket adapter."""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from arb.models import MarketType
from arb.utils.symbols import exchange_symbol, normalize_symbol
from arb.ws.base import BaseWebSocketClient, WsEvent


class BitgetWebSocketClient(BaseWebSocketClient):
    """Bitget public/private WS adapter."""

    public_endpoint = "wss://ws.bitget.com/v2/ws/public"
    private_endpoint = "wss://ws.bitget.com/v2/ws/private"

    def __init__(
        self,
        market_type: MarketType = MarketType.SPOT,
        *,
        api_key: str | None = None,
        api_secret: str | None = None,
        passphrase: str | None = None,
        private: bool = False,
    ) -> None:
        endpoint = self.private_endpoint if private else self.public_endpoint
        super().__init__("bitget", endpoint, heartbeat_interval=30)
        self.market_type = market_type
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase

    def build_subscribe_message(
        self,
        channel: str,
        *,
        symbol: str | None = None,
        market: str | None = None,
    ) -> Mapping[str, Any]:
        if symbol is None:
            raise ValueError("symbol is required for Bitget subscriptions")
        actual_channel = "ticker" if channel == "funding" else channel
        if actual_channel not in {"books", "ticker"}:
            raise ValueError(f"unsupported Bitget channel: {channel}")
        return {
            "op": "subscribe",
            "args": [
                {
                    "instType": self._inst_type(),
                    "channel": actual_channel,
                    "instId": exchange_symbol(symbol, delimiter=""),
                }
            ],
        }

    def build_login_message(self, timestamp: str) -> Mapping[str, Any]:
        if not all((self.api_key, self.api_secret, self.passphrase)):
            raise ValueError("api_key, api_secret and passphrase are required for login")
        digest = hmac.new(
            str(self.api_secret).encode("utf-8"),
            f"{timestamp}GET/user/verify".encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return {
            "op": "login",
            "args": [
                {
                    "apiKey": self.api_key,
                    "passphrase": self.passphrase,
                    "timestamp": timestamp,
                    "sign": base64.b64encode(digest).decode("utf-8"),
                }
            ],
        }

    def build_ping_message(self) -> str:
        return "ping"

    def is_pong_message(self, message: Mapping[str, Any] | str) -> bool:
        if isinstance(message, str):
            return message == "pong"
        return message.get("event") == "pong"

    def parse_message(self, message: Mapping[str, Any]) -> list[WsEvent]:
        if message.get("event") in {"subscribe", "login", "error"}:
            return []
        arg = message.get("arg")
        data = message.get("data", [])
        if not isinstance(arg, Mapping) or not data:
            return []
        channel = str(arg.get("channel"))
        if channel == "books":
            return [self._parse_books(arg, data[0])]
        if channel == "ticker":
            return self._parse_ticker_events(arg, data[0])
        return []

    def _inst_type(self) -> str:
        return "SPOT" if self.market_type is MarketType.SPOT else "USDT-FUTURES"

    def _parse_books(self, arg: Mapping[str, Any], payload: Mapping[str, Any]) -> WsEvent:
        symbol = str(payload.get("instId") or payload.get("symbol") or arg.get("instId"))
        return WsEvent(
            exchange=self.exchange,
            channel="orderbook.update",
            payload={
                "symbol": normalize_symbol(symbol),
                "bids": tuple((Decimal(str(level[0])), Decimal(str(level[1]))) for level in payload.get("bids", [])),
                "asks": tuple((Decimal(str(level[0])), Decimal(str(level[1]))) for level in payload.get("asks", [])),
                "ts": payload.get("ts"),
                "action": message_action(arg, payload),
            },
        )

    def _parse_ticker_events(
        self,
        arg: Mapping[str, Any],
        payload: Mapping[str, Any],
    ) -> list[WsEvent]:
        symbol = str(payload.get("instId") or payload.get("symbol") or arg.get("instId"))
        events = [
            WsEvent(
                exchange=self.exchange,
                channel="ticker.update",
                payload={
                    "symbol": normalize_symbol(symbol),
                    "bid": Decimal(str(payload["bidPr"])),
                    "ask": Decimal(str(payload["askPr"])),
                    "last": Decimal(str(payload["lastPr"])),
                },
            )
        ]
        funding_rate = payload.get("fundingRate")
        if funding_rate is not None:
            events.append(
                WsEvent(
                    exchange=self.exchange,
                    channel="funding.update",
                    payload={
                        "symbol": normalize_symbol(symbol),
                        "funding_rate": Decimal(str(funding_rate)),
                        "next_funding_time": payload.get("nextFundingTime"),
                        "mark_price": (
                            Decimal(str(payload["markPrice"]))
                            if payload.get("markPrice") is not None
                            else None
                        ),
                    },
                )
            )
        return events


def message_action(arg: Mapping[str, Any], payload: Mapping[str, Any]) -> Any:
    return payload.get("action") or arg.get("action")
