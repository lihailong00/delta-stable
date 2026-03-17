"""Bybit REST adapter."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import urlencode

from arb.exchange.base import BaseExchangeClient
from arb.models import Fill, FundingRate, MarketType, Order, OrderBook, OrderBookLevel, OrderStatus, Position, PositionDirection, Side, Ticker
from arb.net.schemas import HttpRequest, JsonValue
from arb.schemas.base import SerializableValue
from arb.utils.symbols import exchange_symbol, normalize_symbol
from arb.ws.schemas import OpArgsMessage

RestTransport = Callable[[HttpRequest], Awaitable[JsonValue]]


def _missing_transport(_: HttpRequest) -> Awaitable[JsonValue]:
    raise RuntimeError("a transport callable must be provided")


class BybitExchange(BaseExchangeClient):
    """Bybit v5 REST adapter."""

    base_url = "https://api.bybit.com"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        recv_window: int = 5000,
        transport: RestTransport | None = None,
    ) -> None:
        super().__init__("bybit")
        self.api_key = api_key
        self.api_secret = api_secret
        self.recv_window = recv_window
        self._transport = transport or _missing_transport

    def sign_request(
        self,
        method: str,
        path: str,
        *,
        query: str = "",
        body: str = "",
        timestamp: str | None = None,
    ) -> Mapping[str, str]:
        ts = timestamp or str(int(time.time() * 1000))
        payload = f"{ts}{self.api_key}{self.recv_window}{query if method.upper() == 'GET' else body}"
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-TIMESTAMP": ts,
            "X-BAPI-RECV-WINDOW": str(self.recv_window),
            "X-BAPI-SIGN": signature,
            "Content-Type": "application/json",
        }

    def build_ws_auth_message(self, expires: int) -> OpArgsMessage:
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            f"GET/realtime{expires}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return OpArgsMessage(op="auth", args=[self.api_key, expires, signature])

    def to_exchange_symbol(
        self,
        symbol: str,
        market_type: MarketType = MarketType.SPOT,
    ) -> str:
        return exchange_symbol(symbol, delimiter="")

    def from_exchange_symbol(
        self,
        symbol: str,
        market_type: MarketType = MarketType.SPOT,
    ) -> str:
        return normalize_symbol(symbol)

    def _category(self, market_type: MarketType) -> str:
        return "spot" if market_type is MarketType.SPOT else "linear"

    async def fetch_ticker(self, symbol: str, market_type: MarketType) -> Ticker:
        payload = await self._request(
            "GET",
            "/v5/market/tickers",
            params={
                "category": self._category(market_type),
                "symbol": self.to_exchange_symbol(symbol, market_type),
            },
        )
        data = self._unwrap(payload)
        bid = Decimal(str(data["bid1Price"]))
        ask = Decimal(str(data["ask1Price"]))
        return Ticker(
            exchange=self.name,
            symbol=self.from_exchange_symbol(str(data["symbol"]), market_type),
            market_type=market_type,
            bid=bid,
            ask=ask,
            last=Decimal(str(data["lastPrice"])),
        )

    async def fetch_orderbook(
        self,
        symbol: str,
        market_type: MarketType,
        limit: int = 50,
    ) -> OrderBook:
        payload = await self._request(
            "GET",
            "/v5/market/orderbook",
            params={
                "category": self._category(market_type),
                "symbol": self.to_exchange_symbol(symbol, market_type),
                "limit": str(limit),
            },
        )
        data = payload["result"]
        return OrderBook(
            exchange=self.name,
            symbol=self.from_exchange_symbol(str(data["s"]), market_type),
            market_type=market_type,
            bids=tuple(
                OrderBookLevel(price=Decimal(str(level[0])), size=Decimal(str(level[1])))
                for level in data.get("b", [])
            ),
            asks=tuple(
                OrderBookLevel(price=Decimal(str(level[0])), size=Decimal(str(level[1])))
                for level in data.get("a", [])
            ),
        )

    async def fetch_funding_rate(self, symbol: str) -> FundingRate:
        payload = await self._request(
            "GET",
            "/v5/market/tickers",
            params={"category": "linear", "symbol": self.to_exchange_symbol(symbol, MarketType.PERPETUAL)},
        )
        data = self._unwrap(payload)
        return FundingRate(
            exchange=self.name,
            symbol=self.from_exchange_symbol(str(data["symbol"]), MarketType.PERPETUAL),
            rate=Decimal(str(data["fundingRate"])),
            predicted_rate=Decimal(str(data.get("fundingRate", "0"))),
            next_funding_time=datetime.fromtimestamp(int(data["nextFundingTime"]) / 1000, tz=timezone.utc),
        )

    async def fetch_balances(self) -> Mapping[str, Decimal]:
        payload = await self._request(
            "GET",
            "/v5/account/wallet-balance",
            params={"accountType": "UNIFIED"},
            signed=True,
        )
        balances: dict[str, Decimal] = {}
        for account in payload.get("result", {}).get("list", []):
            for coin in account.get("coin", []):
                balances[coin["coin"]] = Decimal(str(coin["walletBalance"]))
        return balances

    async def create_order(
        self,
        symbol: str,
        market_type: MarketType,
        side: str,
        quantity: Decimal,
        *,
        price: Decimal | None = None,
        reduce_only: bool = False,
    ) -> Order:
        body: dict[str, SerializableValue] = {
            "category": self._category(market_type),
            "symbol": self.to_exchange_symbol(symbol, market_type),
            "side": side.capitalize(),
            "orderType": "Limit" if price is not None else "Market",
            "qty": format(quantity, "f"),
        }
        if price is not None:
            body["price"] = format(price, "f")
        if market_type is MarketType.PERPETUAL and reduce_only:
            body["reduceOnly"] = True
        payload = await self._request("POST", "/v5/order/create", body=body, signed=True)
        order_id = payload.get("result", {}).get("orderId", "")
        return Order(
            exchange=self.name,
            symbol=symbol,
            market_type=market_type,
            side=Side(side.lower()),
            quantity=quantity,
            price=price,
            status=OrderStatus.NEW,
            order_id=str(order_id),
        )

    async def cancel_order(
        self,
        order_id: str,
        symbol: str,
        market_type: MarketType,
    ) -> Order:
        await self._request(
            "POST",
            "/v5/order/cancel",
            body={
                "category": self._category(market_type),
                "symbol": self.to_exchange_symbol(symbol, market_type),
                "orderId": order_id,
            },
            signed=True,
        )
        return Order(
            exchange=self.name,
            symbol=symbol,
            market_type=market_type,
            side=Side.BUY,
            quantity=Decimal("0"),
            price=None,
            status=OrderStatus.CANCELED,
            order_id=order_id,
        )

    async def fetch_order(
        self,
        order_id: str,
        symbol: str,
        market_type: MarketType,
    ) -> Order:
        payload = await self._request(
            "GET",
            "/v5/order/realtime",
            params={
                "category": self._category(market_type),
                "symbol": self.to_exchange_symbol(symbol, market_type),
                "orderId": order_id,
            },
            signed=True,
        )
        return self._parse_order(self._unwrap(payload), market_type)

    async def fetch_open_orders(
        self,
        symbol: str | None,
        market_type: MarketType,
    ) -> list[Order]:
        params: dict[str, SerializableValue] = {"category": self._category(market_type)}
        if symbol is not None:
            params["symbol"] = self.to_exchange_symbol(symbol, market_type)
        payload = await self._request(
            "GET",
            "/v5/order/realtime",
            params=params,
            signed=True,
        )
        return [self._parse_order(item, market_type) for item in payload.get("result", {}).get("list", [])]

    async def fetch_positions(
        self,
        market_type: MarketType = MarketType.PERPETUAL,
        *,
        symbol: str | None = None,
    ) -> list[Position]:
        if market_type is MarketType.SPOT:
            return []
        params: dict[str, SerializableValue] = {"category": self._category(market_type)}
        if symbol is not None:
            params["symbol"] = self.to_exchange_symbol(symbol, market_type)
        payload = await self._request(
            "GET",
            "/v5/position/list",
            params=params,
            signed=True,
        )
        return [position for item in payload.get("result", {}).get("list", []) if (position := self._parse_position(item)) is not None]

    async def fetch_fills(
        self,
        order_id: str,
        symbol: str,
        market_type: MarketType,
    ) -> list[Fill]:
        payload = await self._request(
            "GET",
            "/v5/execution/list",
            params={
                "category": self._category(market_type),
                "symbol": self.to_exchange_symbol(symbol, market_type),
                "orderId": order_id,
            },
            signed=True,
        )
        return [self._parse_fill(item, market_type) for item in payload.get("result", {}).get("list", [])]

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, SerializableValue] | None = None,
        body: Mapping[str, SerializableValue] | None = None,
        signed: bool = False,
    ) -> JsonValue:
        query = urlencode({key: str(value) for key, value in (params or {}).items()})
        body_text = json.dumps(body or {}, separators=(",", ":")) if body is not None else ""
        headers: dict[str, str] = {}
        if signed:
            headers = dict(
                self.sign_request(
                    method,
                    path,
                    query=query,
                    body=body_text,
                )
            )
        request = HttpRequest(
            method=method,
            url=f"{self.base_url}{path}",
            path=path,
            params=dict(params or {}),
            json_body=dict(body or {}),
            body_text=body_text,
            headers=headers,
            signed=signed,
        )
        return await self._transport(request)

    @staticmethod
    def _unwrap(payload: Mapping[str, object]) -> Mapping[str, object]:
        items = payload.get("result", {}).get("list", [])
        if not items:
            return {}
        return items[0]

    def _parse_order(self, payload: Mapping[str, object], market_type: MarketType) -> Order:
        status_map = {
            "new": OrderStatus.NEW,
            "partiallyfilled": OrderStatus.PARTIALLY_FILLED,
            "filled": OrderStatus.FILLED,
            "cancelled": OrderStatus.CANCELED,
            "rejected": OrderStatus.REJECTED,
            "deactivated": OrderStatus.EXPIRED,
        }
        status_key = str(payload.get("orderStatus", "New")).replace(" ", "").lower()
        return Order(
            exchange=self.name,
            symbol=self.from_exchange_symbol(str(payload["symbol"]), market_type),
            market_type=market_type,
            side=Side(str(payload.get("side", "Buy")).lower()),
            quantity=Decimal(str(payload.get("qty", payload.get("orderQty", "0")))),
            price=Decimal(str(payload["price"])) if payload.get("price") not in (None, "") else None,
            status=status_map.get(status_key, OrderStatus.NEW),
            order_id=str(payload.get("orderId", "")),
            client_order_id=str(payload["orderLinkId"]) if payload.get("orderLinkId") else None,
            filled_quantity=Decimal(str(payload.get("cumExecQty", "0"))),
            average_price=Decimal(str(payload["avgPrice"])) if payload.get("avgPrice") not in (None, "", "0") else None,
            reduce_only=bool(payload.get("reduceOnly", False)),
            raw_status=str(payload.get("orderStatus", "New")),
        )

    def _parse_position(self, payload: Mapping[str, object]) -> Position | None:
        raw_quantity = Decimal(str(payload.get("size", "0")))
        if raw_quantity == 0:
            return None
        side = str(payload.get("side", "Buy")).lower()
        direction = PositionDirection.LONG if side == "buy" else PositionDirection.SHORT
        return Position(
            exchange=self.name,
            symbol=self.from_exchange_symbol(str(payload["symbol"]), MarketType.PERPETUAL),
            market_type=MarketType.PERPETUAL,
            direction=direction,
            quantity=raw_quantity,
            entry_price=Decimal(str(payload.get("avgPrice", "0"))),
            mark_price=Decimal(str(payload.get("markPrice", "0"))),
            unrealized_pnl=Decimal(str(payload.get("unrealisedPnl", payload.get("unrealizedPnl", "0")))),
            liquidation_price=Decimal(str(payload["liqPrice"])) if payload.get("liqPrice") not in (None, "", "0") else None,
            leverage=Decimal(str(payload["leverage"])) if payload.get("leverage") not in (None, "", "0") else None,
            margin_mode=str(payload["tradeMode"]) if payload.get("tradeMode") else None,
            position_id=str(payload["positionIdx"]) if payload.get("positionIdx") is not None else None,
        )

    def _parse_fill(self, payload: Mapping[str, object], market_type: MarketType) -> Fill:
        exec_type = str(payload.get("execType", "")).lower()
        liquidity = "maker" if "maker" in exec_type else ("taker" if exec_type else None)
        return Fill(
            exchange=self.name,
            symbol=self.from_exchange_symbol(str(payload["symbol"]), market_type),
            market_type=market_type,
            side=Side(str(payload.get("side", "Buy")).lower()),
            quantity=Decimal(str(payload.get("execQty", "0"))),
            price=Decimal(str(payload.get("execPrice", "0"))),
            order_id=str(payload.get("orderId", "")),
            fill_id=str(payload.get("execId", "")),
            fee=Decimal(str(payload.get("execFee", "0"))),
            fee_asset=str(payload["feeCurrency"]) if payload.get("feeCurrency") else None,
            liquidity=liquidity,
            ts=datetime.fromtimestamp(int(payload.get("execTime", "0")) / 1000, tz=timezone.utc),
        )
