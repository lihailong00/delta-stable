"""OKX WebSocket adapter."""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Mapping
from decimal import Decimal

from arb.models import MarketType
from arb.utils.symbols import split_symbol
from arb.ws.base import BaseWebSocketClient, WsEvent
from arb.ws.schemas import FundingUpdatePayload, OpArgsMessage, OrderBookUpdatePayload, OrderUpdatePayload, FillUpdatePayload, PositionUpdatePayload, TickerUpdatePayload


class OkxWebSocketClient(BaseWebSocketClient):
    """OKX public/private WS adapter."""

    public_endpoint = "wss://ws.okx.com:8443/ws/v5/public"
    private_endpoint = "wss://ws.okx.com:8443/ws/v5/private"

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
        super().__init__("okx", endpoint, heartbeat_interval=25)
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
        if self.private and channel in {"orders", "positions"}:
            args: dict[str, str] = {"channel": channel}
            if symbol is not None:
                args["instId"] = self.to_exchange_symbol(symbol)
            return OpArgsMessage(op="subscribe", args=[args])
        if symbol is None:
            raise ValueError("symbol is required for OKX subscriptions")
        return OpArgsMessage(
            op="subscribe",
            args=[{"channel": channel, "instId": self.to_exchange_symbol(symbol)}],
        )

    def build_login_message(self, timestamp: str) -> OpArgsMessage:
        if not all((self.api_key, self.api_secret, self.passphrase)):
            raise ValueError("api_key, api_secret and passphrase are required for login")
        digest = hmac.new(
            str(self.api_secret).encode("utf-8"),
            f"{timestamp}GET/users/self/verify".encode("utf-8"),
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

    def build_ping_message(self) -> dict[str, str]:
        return {"event": "ping"}

    def is_pong_message(self, message: Mapping[str, object]) -> bool:
        return message.get("event") == "pong"

    def parse_message(self, message: Mapping[str, object]) -> list[WsEvent]:
        if message.get("event") in {"subscribe", "login", "error"}:
            return []
        arg = message.get("arg")
        data = message.get("data", [])
        if not isinstance(arg, Mapping) or not data:
            return []
        channel = str(arg.get("channel"))
        payload = data[0]
        if channel == "orders":
            return self._parse_private_order(payload)
        if channel == "positions":
            return [self._parse_private_position(payload)]
        if channel == "tickers":
            return [self._parse_ticker(payload)]
        if channel == "books":
            return [self._parse_books(payload)]
        if channel == "funding-rate":
            return [self._parse_funding(payload)]
        return []

    def to_exchange_symbol(self, symbol: str) -> str:
        base, quote = split_symbol(symbol)
        if self.market_type is MarketType.PERPETUAL:
            return f"{base}-{quote}-SWAP"
        return f"{base}-{quote}"

    def _parse_ticker(self, payload: Mapping[str, object]) -> WsEvent:
        return WsEvent(
            exchange=self.exchange,
            channel="ticker.update",
            payload=TickerUpdatePayload(
                symbol=str(payload["instId"]).replace("-SWAP", "").replace("-", "/"),
                bid=Decimal(str(payload["bidPx"])),
                ask=Decimal(str(payload["askPx"])),
                last=Decimal(str(payload["last"])),
            ),
        )

    def _parse_books(self, payload: Mapping[str, object]) -> WsEvent:
        return WsEvent(
            exchange=self.exchange,
            channel="orderbook.update",
            payload=OrderBookUpdatePayload(
                symbol=str(payload["instId"]).replace("-SWAP", "").replace("-", "/"),
                bids=tuple((Decimal(str(level[0])), Decimal(str(level[1]))) for level in payload.get("bids", [])),
                asks=tuple((Decimal(str(level[0])), Decimal(str(level[1]))) for level in payload.get("asks", [])),
                ts=str(payload["ts"]) if payload.get("ts") is not None else None,
            ),
        )

    def _parse_funding(self, payload: Mapping[str, object]) -> WsEvent:
        return WsEvent(
            exchange=self.exchange,
            channel="funding.update",
            payload=FundingUpdatePayload(
                symbol=str(payload["instId"]).replace("-SWAP", "").replace("-", "/"),
                funding_rate=Decimal(str(payload["fundingRate"])),
                next_funding_rate=Decimal(str(payload.get("nextFundingRate", payload["fundingRate"]))),
                next_funding_time=str(payload["nextFundingTime"]) if payload.get("nextFundingTime") is not None else None,
            ),
        )

    def _parse_private_order(self, payload: Mapping[str, object]) -> list[WsEvent]:
        symbol = payload["instId"].replace("-SWAP", "").replace("-", "/")
        events = [
            WsEvent(
                exchange=self.exchange,
                channel="order.update",
                payload=OrderUpdatePayload(
                    symbol=symbol,
                    order_id=str(payload["ordId"]),
                    side=str(payload.get("side", "buy")).lower(),
                    status=str(payload.get("state", "live")).lower(),
                    quantity=Decimal(str(payload.get("sz", "0"))),
                    filled_quantity=Decimal(str(payload.get("accFillSz", "0"))),
                    price=Decimal(str(payload["px"])) if payload.get("px") not in (None, "", "0") else None,
                ),
            )
        ]
        fill_quantity = Decimal(str(payload.get("fillSz", "0")))
        if fill_quantity > 0:
            events.append(
                WsEvent(
                    exchange=self.exchange,
                    channel="fill.update",
                    payload=FillUpdatePayload(
                        symbol=symbol,
                        order_id=str(payload["ordId"]),
                        fill_id=str(payload.get("tradeId", "")),
                        side=str(payload.get("side", "buy")).lower(),
                        quantity=fill_quantity,
                        price=Decimal(str(payload.get("fillPx", "0"))),
                        fee=Decimal(str(payload.get("fee", "0"))),
                        fee_asset=str(payload["feeCcy"]) if payload.get("feeCcy") is not None else None,
                    ),
                )
            )
        return events

    def _parse_private_position(self, payload: Mapping[str, object]) -> WsEvent:
        quantity = Decimal(str(payload.get("pos", "0")))
        direction = "long" if quantity > 0 or str(payload.get("posSide", "")).lower() == "long" else "short"
        return WsEvent(
            exchange=self.exchange,
            channel="position.update",
            payload=PositionUpdatePayload(
                symbol=str(payload["instId"]).replace("-SWAP", "").replace("-", "/"),
                direction=direction,
                quantity=abs(quantity),
                entry_price=Decimal(str(payload.get("avgPx", "0"))),
                mark_price=Decimal(str(payload.get("markPx", "0"))),
                unrealized_pnl=Decimal(str(payload.get("upl", "0"))),
            ),
        )
