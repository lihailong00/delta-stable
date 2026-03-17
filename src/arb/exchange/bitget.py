"""Bitget REST adapter."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

from arb.exchange.base import BaseExchangeClient
from arb.models import Fill, FundingRate, MarketType, Order, OrderBook, OrderBookLevel, OrderStatus, Position, PositionDirection, Side, Ticker
from arb.utils.symbols import exchange_symbol, normalize_symbol, split_symbol

RestTransport = Callable[[dict[str, Any]], Awaitable[Any]]


def _missing_transport(_: dict[str, Any]) -> Awaitable[Any]:
    raise RuntimeError("a transport callable must be provided")


class BitgetExchange(BaseExchangeClient):
    """Bitget v2 REST adapter."""

    base_url = "https://api.bitget.com"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        passphrase: str,
        *,
        product_type: str = "USDT-FUTURES",
        locale: str = "en-US",
        transport: RestTransport | None = None,
    ) -> None:
        super().__init__("bitget")
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.product_type = product_type.upper()
        self.locale = locale
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
        request_path = f"{path}?{query}" if query else path
        prehash = f"{ts}{method.upper()}{request_path}{body}"
        digest = hmac.new(
            self.api_secret.encode("utf-8"),
            prehash.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": base64.b64encode(digest).decode("utf-8"),
            "ACCESS-TIMESTAMP": ts,
            "ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
            "locale": self.locale,
        }

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

    async def fetch_ticker(self, symbol: str, market_type: MarketType) -> Ticker:
        path = "/api/v2/spot/market/tickers" if market_type is MarketType.SPOT else "/api/v2/mix/market/ticker"
        params = {"symbol": self.to_exchange_symbol(symbol, market_type)}
        if market_type is MarketType.PERPETUAL:
            params["productType"] = self.product_type
        payload = await self._request("GET", path, params=params)
        data = self._unwrap(payload)
        return Ticker(
            exchange=self.name,
            symbol=self.from_exchange_symbol(str(data["symbol"]), market_type),
            market_type=market_type,
            bid=Decimal(str(data["bidPr"])),
            ask=Decimal(str(data["askPr"])),
            last=Decimal(str(data["lastPr"])),
        )

    async def fetch_orderbook(
        self,
        symbol: str,
        market_type: MarketType,
        limit: int = 20,
    ) -> OrderBook:
        if market_type is MarketType.SPOT:
            payload = await self._request(
                "GET",
                "/api/v2/spot/market/orderbook",
                params={
                    "symbol": self.to_exchange_symbol(symbol, market_type),
                    "type": "step0",
                    "limit": str(limit),
                },
            )
        else:
            payload = await self._request(
                "GET",
                "/api/v2/mix/market/merge-depth",
                params={
                    "symbol": self.to_exchange_symbol(symbol, market_type),
                    "productType": self.product_type,
                    "precision": "scale0",
                    "limit": str(limit),
                },
            )
        data = self._unwrap(payload)
        return OrderBook(
            exchange=self.name,
            symbol=symbol,
            market_type=market_type,
            bids=tuple(
                OrderBookLevel(price=Decimal(str(level[0])), size=Decimal(str(level[1])))
                for level in data.get("bids", [])
            ),
            asks=tuple(
                OrderBookLevel(price=Decimal(str(level[0])), size=Decimal(str(level[1])))
                for level in data.get("asks", [])
            ),
        )

    async def fetch_funding_rate(self, symbol: str) -> FundingRate:
        payload = await self._request(
            "GET",
            "/api/v2/mix/market/current-fund-rate",
            params={
                "symbol": self.to_exchange_symbol(symbol, MarketType.PERPETUAL),
                "productType": self.product_type,
            },
        )
        data = self._unwrap(payload)
        return FundingRate(
            exchange=self.name,
            symbol=self.from_exchange_symbol(str(data["symbol"]), MarketType.PERPETUAL),
            rate=Decimal(str(data["fundingRate"])),
            predicted_rate=Decimal(str(data.get("fundingRate", "0"))),
            next_funding_time=datetime.fromtimestamp(int(data["nextUpdate"]) / 1000, tz=timezone.utc),
        )

    async def fetch_balances(self) -> Mapping[str, Decimal]:
        payload = await self._request(
            "GET",
            "/api/v2/spot/account/assets",
            params={"assetType": "all"},
            signed=True,
        )
        balances: dict[str, Decimal] = {}
        for item in payload.get("data", []):
            balances[item["coin"].upper()] = (
                Decimal(str(item.get("available", "0")))
                + Decimal(str(item.get("frozen", "0")))
                + Decimal(str(item.get("locked", "0")))
            )
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
        if market_type is MarketType.SPOT:
            body: dict[str, Any] = {
                "symbol": self.to_exchange_symbol(symbol, market_type),
                "side": side,
                "orderType": "limit" if price is not None else "market",
                "force": "gtc",
                "size": format(quantity, "f"),
            }
            if price is not None:
                body["price"] = format(price, "f")
            payload = await self._request(
                "POST",
                "/api/v2/spot/trade/place-order",
                body=body,
                signed=True,
            )
            order_id = payload.get("data", {}).get("orderId", "")
        else:
            base, quote = split_symbol(symbol)
            body = {
                "symbol": self.to_exchange_symbol(symbol, market_type),
                "productType": self.product_type,
                "marginMode": "crossed",
                "marginCoin": quote,
                "side": side,
                "tradeSide": "close" if reduce_only else "open",
                "orderType": "limit" if price is not None else "market",
                "size": format(quantity, "f"),
            }
            if price is not None:
                body["price"] = format(price, "f")
                body["force"] = "gtc"
            payload = await self._request(
                "POST",
                "/api/v2/mix/order/place-order",
                body=body,
                signed=True,
            )
            order_id = payload.get("data", {}).get("orderId", "")
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
        if market_type is MarketType.SPOT:
            body = {"symbol": self.to_exchange_symbol(symbol, market_type), "orderId": order_id}
            await self._request(
                "POST",
                "/api/v2/spot/trade/cancel-order",
                body=body,
                signed=True,
            )
        else:
            _, quote = split_symbol(symbol)
            body = {
                "symbol": self.to_exchange_symbol(symbol, market_type),
                "productType": self.product_type,
                "marginCoin": quote,
                "orderId": order_id,
            }
            await self._request(
                "POST",
                "/api/v2/mix/order/cancel-order",
                body=body,
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
        if market_type is MarketType.SPOT:
            payload = await self._request(
                "GET",
                "/api/v2/spot/trade/orderInfo",
                params={"symbol": self.to_exchange_symbol(symbol, market_type), "orderId": order_id},
                signed=True,
            )
        else:
            payload = await self._request(
                "GET",
                "/api/v2/mix/order/detail",
                params={
                    "symbol": self.to_exchange_symbol(symbol, market_type),
                    "productType": self.product_type,
                    "orderId": order_id,
                },
                signed=True,
            )
        return self._parse_order(self._unwrap(payload), symbol, market_type)

    async def fetch_open_orders(
        self,
        symbol: str | None,
        market_type: MarketType,
    ) -> list[Order]:
        if market_type is MarketType.SPOT:
            params: dict[str, Any] = {}
            if symbol is not None:
                params["symbol"] = self.to_exchange_symbol(symbol, market_type)
            payload = await self._request(
                "GET",
                "/api/v2/spot/trade/unfilled-orders",
                params=params,
                signed=True,
            )
        else:
            params = {"productType": self.product_type}
            if symbol is not None:
                params["symbol"] = self.to_exchange_symbol(symbol, market_type)
            payload = await self._request(
                "GET",
                "/api/v2/mix/order/orders-pending",
                params=params,
                signed=True,
            )
        return [self._parse_order(item, symbol or "", market_type) for item in payload.get("data", [])]

    async def fetch_positions(
        self,
        market_type: MarketType = MarketType.PERPETUAL,
        *,
        symbol: str | None = None,
    ) -> list[Position]:
        if market_type is MarketType.SPOT:
            return []
        params: dict[str, Any] = {"productType": self.product_type}
        endpoint = "/api/v2/mix/position/all-position"
        if symbol is not None:
            endpoint = "/api/v2/mix/position/single-position"
            params["symbol"] = self.to_exchange_symbol(symbol, market_type)
        payload = await self._request(
            "GET",
            endpoint,
            params=params,
            signed=True,
        )
        data = payload.get("data", [])
        if isinstance(data, dict):
            data = [data]
        return [position for item in data if (position := self._parse_position(item)) is not None]

    async def fetch_fills(
        self,
        order_id: str,
        symbol: str,
        market_type: MarketType,
    ) -> list[Fill]:
        if market_type is MarketType.SPOT:
            payload = await self._request(
                "GET",
                "/api/v2/spot/trade/fills",
                params={"symbol": self.to_exchange_symbol(symbol, market_type), "orderId": order_id},
                signed=True,
            )
        else:
            payload = await self._request(
                "GET",
                "/api/v2/mix/order/fills",
                params={
                    "symbol": self.to_exchange_symbol(symbol, market_type),
                    "productType": self.product_type,
                    "orderId": order_id,
                },
                signed=True,
            )
        data = payload.get("data", [])
        if isinstance(data, dict):
            data = data.get("fills", data.get("entrustedList", []))
        return [self._parse_fill(item, symbol, market_type) for item in data]

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
        signed: bool = False,
    ) -> Any:
        query = urlencode({key: str(value) for key, value in (params or {}).items()})
        body_text = json.dumps(body or {}, separators=(",", ":")) if body is not None else ""
        headers: dict[str, str] = {}
        if signed:
            headers = dict(self.sign_request(method, path, query=query, body=body_text))
        request = {
            "method": method,
            "url": f"{self.base_url}{path}",
            "path": path,
            "query": query,
            "params": dict(params or {}),
            "body": body or {},
            "body_text": body_text,
            "headers": headers,
            "signed": signed,
        }
        return await self._transport(request)

    def _unwrap(self, payload: Mapping[str, Any]) -> Any:
        code = str(payload.get("code", ""))
        if code and code != "00000":
            raise RuntimeError(f"Bitget request failed: {code} {payload.get('msg', payload.get('message', ''))}")
        data = payload.get("data")
        if isinstance(data, list):
            if not data:
                raise RuntimeError("Bitget returned an empty data array")
            return data[0]
        return data

    def _parse_order(self, payload: Mapping[str, Any], symbol: str, market_type: MarketType) -> Order:
        status_map = {
            "new": OrderStatus.NEW,
            "live": OrderStatus.NEW,
            "partially_filled": OrderStatus.PARTIALLY_FILLED,
            "partial_fill": OrderStatus.PARTIALLY_FILLED,
            "partial-fill": OrderStatus.PARTIALLY_FILLED,
            "filled": OrderStatus.FILLED,
            "full-fill": OrderStatus.FILLED,
            "cancelled": OrderStatus.CANCELED,
            "canceled": OrderStatus.CANCELED,
            "rejected": OrderStatus.REJECTED,
        }
        status_key = str(payload.get("status", payload.get("state", "new"))).replace(" ", "_").replace("-", "_").lower()
        side = str(payload.get("side", "buy")).lower()
        if side in {"open_short", "close_long"}:
            side = "sell"
        elif side in {"open_long", "close_short"}:
            side = "buy"
        parsed_symbol = symbol or self.from_exchange_symbol(str(payload.get("symbol", "")), market_type)
        return Order(
            exchange=self.name,
            symbol=parsed_symbol,
            market_type=market_type,
            side=Side(side),
            quantity=Decimal(str(payload.get("size", payload.get("baseVolume", payload.get("qty", "0"))))),
            price=Decimal(str(payload["price"])) if payload.get("price") not in (None, "") else None,
            status=status_map.get(status_key, OrderStatus.NEW),
            order_id=str(payload.get("orderId", payload.get("id", ""))),
            client_order_id=str(payload["clientOid"]) if payload.get("clientOid") else None,
            filled_quantity=Decimal(str(payload.get("baseVolume", payload.get("filledQty", payload.get("filledSize", "0"))))),
            average_price=Decimal(str(payload["priceAvg"])) if payload.get("priceAvg") not in (None, "", "0") else None,
            reduce_only=str(payload.get("tradeSide", "")).lower() == "close",
            raw_status=str(payload.get("status", payload.get("state", "new"))),
        )

    def _parse_position(self, payload: Mapping[str, Any]) -> Position | None:
        raw_quantity = Decimal(str(payload.get("total", payload.get("openDelegateSize", payload.get("holdVol", "0")))))
        if raw_quantity == 0:
            return None
        hold_side = str(payload.get("holdSide", payload.get("positionSide", "long"))).lower()
        direction = PositionDirection.LONG if hold_side == "long" else PositionDirection.SHORT
        return Position(
            exchange=self.name,
            symbol=self.from_exchange_symbol(str(payload.get("symbol", "")), MarketType.PERPETUAL),
            market_type=MarketType.PERPETUAL,
            direction=direction,
            quantity=raw_quantity,
            entry_price=Decimal(str(payload.get("openPriceAvg", payload.get("averageOpenPrice", "0")))),
            mark_price=Decimal(str(payload.get("markPrice", payload.get("marketPrice", "0")))),
            unrealized_pnl=Decimal(str(payload.get("unrealizedPL", payload.get("upl", "0")))),
            liquidation_price=Decimal(str(payload["liqPx"])) if payload.get("liqPx") not in (None, "", "0") else None,
            leverage=Decimal(str(payload["leverage"])) if payload.get("leverage") not in (None, "", "0") else None,
            margin_mode=str(payload["marginMode"]) if payload.get("marginMode") else None,
        )

    def _parse_fill(self, payload: Mapping[str, Any], symbol: str, market_type: MarketType) -> Fill:
        side = str(payload.get("side", "buy")).lower()
        if side in {"open_short", "close_long"}:
            side = "sell"
        elif side in {"open_long", "close_short"}:
            side = "buy"
        liquidity = str(payload["tradeScope"]).lower() if payload.get("tradeScope") else None
        ts_value = payload.get("fillTime", payload.get("cTime", "0"))
        return Fill(
            exchange=self.name,
            symbol=symbol,
            market_type=market_type,
            side=Side(side),
            quantity=Decimal(str(payload.get("size", payload.get("fillQty", payload.get("baseVolume", "0"))))),
            price=Decimal(str(payload.get("priceAvg", payload.get("fillPrice", payload.get("price", "0"))))),
            order_id=str(payload.get("orderId", payload.get("id", ""))),
            fill_id=str(payload.get("tradeId", payload.get("fillId", ""))),
            fee=Decimal(str(payload.get("fee", "0"))),
            fee_asset=str(payload["feeCoin"]) if payload.get("feeCoin") else None,
            liquidity=liquidity,
            ts=datetime.fromtimestamp(int(ts_value) / 1000, tz=timezone.utc),
        )
