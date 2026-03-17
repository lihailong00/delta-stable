"""Binance REST adapter."""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

from arb.exchange.base import BaseExchangeClient
from arb.models import Fill, FundingRate, MarketType, Order, OrderBook, OrderBookLevel, OrderStatus, Position, PositionDirection, Side, Ticker
from arb.utils.symbols import exchange_symbol, normalize_symbol

RestTransport = Callable[[dict[str, Any]], Awaitable[Any]]


def _missing_transport(_: dict[str, Any]) -> Awaitable[Any]:
    raise RuntimeError("a transport callable must be provided")


def _utc_from_millis(value: int | str) -> datetime:
    return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)


def _stringify(value: Any) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


class BinanceExchange(BaseExchangeClient):
    """Binance spot and USD-M futures REST adapter."""

    spot_base_url = "https://api.binance.com"
    futures_base_url = "https://fapi.binance.com"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        transport: RestTransport | None = None,
    ) -> None:
        super().__init__("binance")
        self.api_key = api_key
        self.api_secret = api_secret
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
        payload = f"{query}{body}"
        if timestamp is not None:
            payload = f"{payload}&timestamp={timestamp}" if payload else f"timestamp={timestamp}"
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {"X-MBX-APIKEY": self.api_key, "X-MBX-SIGNATURE": signature}

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

    def sign_params(
        self,
        params: Mapping[str, Any],
        *,
        timestamp: int | None = None,
    ) -> dict[str, str]:
        encoded: dict[str, str] = {key: _stringify(value) for key, value in params.items()}
        encoded["timestamp"] = str(timestamp or int(time.time() * 1000))
        payload = urlencode(encoded)
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        encoded["signature"] = signature
        return encoded

    async def fetch_ticker(self, symbol: str, market_type: MarketType) -> Ticker:
        path = "/api/v3/ticker/bookTicker" if market_type is MarketType.SPOT else "/fapi/v1/ticker/bookTicker"
        payload = await self._request(
            "GET",
            path,
            market_type=market_type,
            params={"symbol": self.to_exchange_symbol(symbol, market_type)},
        )
        return self._parse_ticker(payload, market_type)

    async def fetch_orderbook(
        self,
        symbol: str,
        market_type: MarketType,
        limit: int = 20,
    ) -> OrderBook:
        path = "/api/v3/depth" if market_type is MarketType.SPOT else "/fapi/v1/depth"
        payload = await self._request(
            "GET",
            path,
            market_type=market_type,
            params={"symbol": self.to_exchange_symbol(symbol, market_type), "limit": limit},
        )
        return self._parse_orderbook(payload, symbol, market_type)

    async def fetch_funding_rate(self, symbol: str) -> FundingRate:
        payload = await self._request(
            "GET",
            "/fapi/v1/premiumIndex",
            market_type=MarketType.PERPETUAL,
            params={"symbol": self.to_exchange_symbol(symbol, MarketType.PERPETUAL)},
        )
        return self._parse_funding_rate(payload)

    async def fetch_balances(self) -> Mapping[str, Decimal]:
        payload = await self._request(
            "GET",
            "/api/v3/account",
            market_type=MarketType.SPOT,
            params={},
            signed=True,
        )
        balances = payload.get("balances", [])
        return {
            item["asset"]: Decimal(item["free"]) + Decimal(item.get("locked", "0"))
            for item in balances
        }

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
        path = "/api/v3/order" if market_type is MarketType.SPOT else "/fapi/v1/order"
        params: dict[str, Any] = {
            "symbol": self.to_exchange_symbol(symbol, market_type),
            "side": side.upper(),
            "quantity": quantity,
            "type": "LIMIT" if price is not None else "MARKET",
        }
        if price is not None:
            params["price"] = price
            params["timeInForce"] = "GTC"
        if market_type is MarketType.PERPETUAL and reduce_only:
            params["reduceOnly"] = True
        payload = await self._request(
            "POST",
            path,
            market_type=market_type,
            params=params,
            signed=True,
        )
        return self._parse_order(payload, market_type)

    async def cancel_order(
        self,
        order_id: str,
        symbol: str,
        market_type: MarketType,
    ) -> Order:
        path = "/api/v3/order" if market_type is MarketType.SPOT else "/fapi/v1/order"
        payload = await self._request(
            "DELETE",
            path,
            market_type=market_type,
            params={
                "symbol": self.to_exchange_symbol(symbol, market_type),
                "orderId": order_id,
            },
            signed=True,
        )
        return self._parse_order(payload, market_type)

    async def fetch_order(
        self,
        order_id: str,
        symbol: str,
        market_type: MarketType,
    ) -> Order:
        path = "/api/v3/order" if market_type is MarketType.SPOT else "/fapi/v1/order"
        payload = await self._request(
            "GET",
            path,
            market_type=market_type,
            params={
                "symbol": self.to_exchange_symbol(symbol, market_type),
                "orderId": order_id,
            },
            signed=True,
        )
        return self._parse_order(payload, market_type)

    async def fetch_open_orders(
        self,
        symbol: str | None,
        market_type: MarketType,
    ) -> list[Order]:
        path = "/api/v3/openOrders" if market_type is MarketType.SPOT else "/fapi/v1/openOrders"
        params: dict[str, Any] = {}
        if symbol is not None:
            params["symbol"] = self.to_exchange_symbol(symbol, market_type)
        payload = await self._request(
            "GET",
            path,
            market_type=market_type,
            params=params,
            signed=True,
        )
        return [self._parse_order(item, market_type) for item in payload]

    async def fetch_positions(
        self,
        market_type: MarketType = MarketType.PERPETUAL,
        *,
        symbol: str | None = None,
    ) -> list[Position]:
        if market_type is MarketType.SPOT:
            return []
        params: dict[str, Any] = {}
        if symbol is not None:
            params["symbol"] = self.to_exchange_symbol(symbol, market_type)
        payload = await self._request(
            "GET",
            "/fapi/v2/positionRisk",
            market_type=market_type,
            params=params,
            signed=True,
        )
        return [position for item in payload if (position := self._parse_position(item)) is not None]

    async def fetch_fills(
        self,
        order_id: str,
        symbol: str,
        market_type: MarketType,
    ) -> list[Fill]:
        path = "/api/v3/myTrades" if market_type is MarketType.SPOT else "/fapi/v1/userTrades"
        payload = await self._request(
            "GET",
            path,
            market_type=market_type,
            params={
                "symbol": self.to_exchange_symbol(symbol, market_type),
                "orderId": order_id,
            },
            signed=True,
        )
        return [self._parse_fill(item, symbol, market_type) for item in payload]

    async def _request(
        self,
        method: str,
        path: str,
        *,
        market_type: MarketType,
        params: Mapping[str, Any],
        signed: bool = False,
    ) -> Any:
        payload_params = dict(params)
        headers: dict[str, str] = {}
        if signed:
            payload_params = self.sign_params(payload_params)
            headers["X-MBX-APIKEY"] = self.api_key
        base_url = self.spot_base_url if market_type is MarketType.SPOT else self.futures_base_url
        request = {
            "method": method,
            "url": f"{base_url}{path}",
            "path": path,
            "headers": headers,
            "params": payload_params,
            "market_type": market_type.value,
            "signed": signed,
        }
        return await self._transport(request)

    def _parse_ticker(self, payload: Mapping[str, Any], market_type: MarketType) -> Ticker:
        symbol = self.from_exchange_symbol(str(payload["symbol"]), market_type)
        bid = Decimal(str(payload.get("bidPrice", payload.get("b"))))
        ask = Decimal(str(payload.get("askPrice", payload.get("a"))))
        last = (bid + ask) / Decimal("2")
        return Ticker(
            exchange=self.name,
            symbol=symbol,
            market_type=market_type,
            bid=bid,
            ask=ask,
            last=last,
        )

    def _parse_orderbook(
        self,
        payload: Mapping[str, Any],
        symbol: str,
        market_type: MarketType,
    ) -> OrderBook:
        bids = tuple(
            OrderBookLevel(price=Decimal(str(price)), size=Decimal(str(size)))
            for price, size in payload.get("bids", [])
        )
        asks = tuple(
            OrderBookLevel(price=Decimal(str(price)), size=Decimal(str(size)))
            for price, size in payload.get("asks", [])
        )
        return OrderBook(
            exchange=self.name,
            symbol=symbol,
            market_type=market_type,
            bids=bids,
            asks=asks,
        )

    def _parse_funding_rate(self, payload: Mapping[str, Any]) -> FundingRate:
        return FundingRate(
            exchange=self.name,
            symbol=self.from_exchange_symbol(str(payload["symbol"]), MarketType.PERPETUAL),
            rate=Decimal(str(payload["lastFundingRate"])),
            next_funding_time=_utc_from_millis(payload["nextFundingTime"]),
            predicted_rate=Decimal(str(payload["lastFundingRate"])),
        )

    def _parse_order(self, payload: Mapping[str, Any], market_type: MarketType) -> Order:
        status_map = {
            "NEW": OrderStatus.NEW,
            "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
            "FILLED": OrderStatus.FILLED,
            "CANCELED": OrderStatus.CANCELED,
            "REJECTED": OrderStatus.REJECTED,
            "EXPIRED": OrderStatus.EXPIRED,
        }
        return Order(
            exchange=self.name,
            symbol=self.from_exchange_symbol(str(payload["symbol"]), market_type),
            market_type=market_type,
            side=Side(str(payload["side"]).lower()),
            quantity=Decimal(str(payload.get("origQty", payload.get("orig_quantity", "0")))),
            price=Decimal(str(payload["price"])) if payload.get("price") not in (None, "") else None,
            status=status_map[str(payload.get("status", "NEW")).upper()],
            order_id=str(payload.get("orderId", payload.get("order_id", ""))),
            client_order_id=(
                str(payload["clientOrderId"])
                if payload.get("clientOrderId") not in (None, "")
                else None
            ),
            filled_quantity=Decimal(str(payload.get("executedQty", payload.get("executed_quantity", "0")))),
            average_price=(
                Decimal(str(payload["avgPrice"]))
                if payload.get("avgPrice") not in (None, "", "0")
                else None
            ),
            reduce_only=bool(payload.get("reduceOnly", False)),
            raw_status=str(payload.get("status", "NEW")),
        )

    def _parse_position(self, payload: Mapping[str, Any]) -> Position | None:
        raw_quantity = Decimal(str(payload.get("positionAmt", payload.get("position_amount", "0"))))
        if raw_quantity == 0:
            return None
        direction = (
            PositionDirection.LONG
            if raw_quantity > 0 or str(payload.get("positionSide", "")).upper() == "LONG"
            else PositionDirection.SHORT
        )
        symbol = self.from_exchange_symbol(str(payload["symbol"]), MarketType.PERPETUAL)
        return Position(
            exchange=self.name,
            symbol=symbol,
            market_type=MarketType.PERPETUAL,
            direction=direction,
            quantity=abs(raw_quantity),
            entry_price=Decimal(str(payload.get("entryPrice", "0"))),
            mark_price=Decimal(str(payload.get("markPrice", "0"))),
            unrealized_pnl=Decimal(str(payload.get("unRealizedProfit", payload.get("unrealizedProfit", "0")))),
            liquidation_price=(
                Decimal(str(payload["liquidationPrice"]))
                if payload.get("liquidationPrice") not in (None, "", "0")
                else None
            ),
            leverage=(
                Decimal(str(payload["leverage"]))
                if payload.get("leverage") not in (None, "")
                else None
            ),
            margin_mode=str(payload["marginType"]) if payload.get("marginType") else None,
        )

    def _parse_fill(self, payload: Mapping[str, Any], symbol: str, market_type: MarketType) -> Fill:
        if payload.get("side") is not None:
            side = Side(str(payload["side"]).lower())
        else:
            side = Side.BUY if bool(payload.get("isBuyer", True)) else Side.SELL
        liquidity = "maker" if bool(payload.get("isMaker", False)) else "taker"
        return Fill(
            exchange=self.name,
            symbol=symbol,
            market_type=market_type,
            side=side,
            quantity=Decimal(str(payload.get("qty", payload.get("executedQty", "0")))),
            price=Decimal(str(payload.get("price", payload.get("avgPrice", "0")))),
            order_id=str(payload.get("orderId", "")),
            fill_id=str(payload.get("id", payload.get("tradeId", ""))),
            fee=Decimal(str(payload.get("commission", payload.get("commissionAmount", "0")))),
            fee_asset=str(payload["commissionAsset"]) if payload.get("commissionAsset") else None,
            liquidity=liquidity,
            ts=_utc_from_millis(payload.get("time", payload.get("tradeTime", int(time.time() * 1000)))),
        )
