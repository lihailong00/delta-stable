"""Bitget WebSocket adapter."""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Mapping
from decimal import Decimal

from arb.models import MarketType
from arb.utils.symbols import exchange_symbol, normalize_symbol
from arb.ws.base import BaseWebSocketClient, WsEvent
from arb.ws.schemas import FillUpdatePayload, FundingUpdatePayload, OpArgsMessage, OrderBookUpdatePayload, OrderUpdatePayload, PositionUpdatePayload, TickerUpdatePayload


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
        self.private = private

    def build_subscribe_message(
        self,
        channel: str,
        *,
        symbol: str | None = None,
        market: str | None = None,
    ) -> OpArgsMessage:
        if self.private and channel in {"orders", "positions", "fills"}:
            arg: dict[str, str] = {"instType": self._inst_type(), "channel": channel}
            if symbol is not None:
                arg["instId"] = exchange_symbol(symbol, delimiter="")
            return OpArgsMessage(op="subscribe", args=[arg])
        if symbol is None:
            raise ValueError("symbol is required for Bitget subscriptions")
        actual_channel = "ticker" if channel == "funding" else channel
        if actual_channel not in {"books", "ticker"}:
            raise ValueError(f"unsupported Bitget channel: {channel}")
        return OpArgsMessage(
            op="subscribe",
            args=[
                {
                    "instType": self._inst_type(),
                    "channel": actual_channel,
                    "instId": exchange_symbol(symbol, delimiter=""),
                }
            ],
        )

    def build_login_message(self, timestamp: str) -> OpArgsMessage:
        if not all((self.api_key, self.api_secret, self.passphrase)):
            raise ValueError("api_key, api_secret and passphrase are required for login")
        digest = hmac.new(
            str(self.api_secret).encode("utf-8"),
            f"{timestamp}GET/user/verify".encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return OpArgsMessage(
            op="login",
            args=[
                {
                    "apiKey": str(self.api_key),
                    "passphrase": str(self.passphrase),
                    "timestamp": timestamp,
                    "sign": base64.b64encode(digest).decode("utf-8"),
                }
            ],
        )

    def build_ping_message(self) -> str:
        return "ping"

    def is_pong_message(self, message: Mapping[str, object] | str) -> bool:
        if isinstance(message, str):
            return message == "pong"
        return message.get("event") == "pong"

    def parse_message(self, message: Mapping[str, object]) -> list[WsEvent]:
        if message.get("event") in {"subscribe", "login", "error"}:
            return []
        arg = message.get("arg")
        data = message.get("data", [])
        if not isinstance(arg, Mapping) or not data:
            return []
        channel = str(arg.get("channel"))
        if channel == "orders":
            return self._parse_private_orders(data)
        if channel == "positions":
            return self._parse_private_positions(data)
        if channel == "fills":
            return self._parse_private_fills(data)
        if channel == "books":
            return [self._parse_books(arg, data[0])]
        if channel == "ticker":
            return self._parse_ticker_events(arg, data[0])
        return []

    def _inst_type(self) -> str:
        return "SPOT" if self.market_type is MarketType.SPOT else "USDT-FUTURES"

    def _parse_books(self, arg: Mapping[str, object], payload: Mapping[str, object]) -> WsEvent:
        symbol = str(payload.get("instId") or payload.get("symbol") or arg.get("instId"))
        return WsEvent(
            exchange=self.exchange,
            channel="orderbook.update",
            payload=OrderBookUpdatePayload(
                symbol=normalize_symbol(symbol),
                bids=tuple((Decimal(str(level[0])), Decimal(str(level[1]))) for level in payload.get("bids", [])),
                asks=tuple((Decimal(str(level[0])), Decimal(str(level[1]))) for level in payload.get("asks", [])),
                ts=str(payload["ts"]) if payload.get("ts") is not None else None,
                action=message_action(arg, payload),
            ),
        )

    def _parse_ticker_events(
        self,
        arg: Mapping[str, object],
        payload: Mapping[str, object],
    ) -> list[WsEvent]:
        symbol = str(payload.get("instId") or payload.get("symbol") or arg.get("instId"))
        events = [
            WsEvent(
                exchange=self.exchange,
                channel="ticker.update",
                payload=TickerUpdatePayload(
                    symbol=normalize_symbol(symbol),
                    bid=Decimal(str(payload["bidPr"])),
                    ask=Decimal(str(payload["askPr"])),
                    last=Decimal(str(payload["lastPr"])),
                ),
            )
        ]
        funding_rate = payload.get("fundingRate")
        if funding_rate is not None:
            events.append(
                WsEvent(
                    exchange=self.exchange,
                    channel="funding.update",
                    payload=FundingUpdatePayload(
                        symbol=normalize_symbol(symbol),
                        funding_rate=Decimal(str(funding_rate)),
                        next_funding_time=str(payload["nextFundingTime"]) if payload.get("nextFundingTime") is not None else None,
                        mark_price=Decimal(str(payload["markPrice"])) if payload.get("markPrice") is not None else None,
                    ),
                )
            )
        return events

    def _parse_private_orders(self, data: list[Mapping[str, object]]) -> list[WsEvent]:
        return [
            WsEvent(
                exchange=self.exchange,
                channel="order.update",
                payload=OrderUpdatePayload(
                    symbol=normalize_symbol(str(item.get("instId", ""))),
                    order_id=str(item.get("ordId", "")),
                    side=str(item.get("side", "buy")).lower(),
                    status=str(item.get("status", "new")).lower(),
                    quantity=Decimal(str(item.get("sz", "0"))),
                    filled_quantity=Decimal(str(item.get("accFillSz", "0"))),
                    price=Decimal(str(item["px"])) if item.get("px") not in (None, "", "0") else None,
                ),
            )
            for item in data
        ]

    def _parse_private_positions(self, data: list[Mapping[str, object]]) -> list[WsEvent]:
        events: list[WsEvent] = []
        for item in data:
            quantity = Decimal(str(item.get("total", item.get("pos", "0"))))
            if quantity == 0:
                continue
            direction = str(item.get("holdSide", "long")).lower()
            events.append(
                WsEvent(
                    exchange=self.exchange,
                    channel="position.update",
                    payload=PositionUpdatePayload(
                        symbol=normalize_symbol(str(item.get("instId", ""))),
                        direction=direction,
                        quantity=abs(quantity),
                        entry_price=Decimal(str(item.get("avgOpenPrice", item.get("entryPrice", "0")))),
                        mark_price=Decimal(str(item.get("markPrice", "0"))),
                        unrealized_pnl=Decimal(str(item.get("unrealizedPL", item.get("upl", "0")))),
                    ),
                )
            )
        return events

    def _parse_private_fills(self, data: list[Mapping[str, object]]) -> list[WsEvent]:
        return [
            WsEvent(
                exchange=self.exchange,
                channel="fill.update",
                payload=FillUpdatePayload(
                    symbol=normalize_symbol(str(item.get("instId", ""))),
                    order_id=str(item.get("ordId", "")),
                    fill_id=str(item.get("tradeId", "")),
                    side=str(item.get("side", "buy")).lower(),
                    quantity=Decimal(str(item.get("fillSz", "0"))),
                    price=Decimal(str(item.get("fillPx", "0"))),
                    fee=Decimal(str(item.get("fee", "0"))),
                    fee_asset=str(item["feeCoin"]) if item.get("feeCoin") is not None else None,
                ),
            )
            for item in data
        ]


def message_action(arg: Mapping[str, object], payload: Mapping[str, object]) -> str | None:
    action = payload.get("action") or arg.get("action")
    return str(action) if action is not None else None
