"""OKX REST adapter."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

from arb.exchange.base import BaseExchangeClient
from arb.models import Fill, FundingRate, MarketType, Order, OrderBook, OrderBookLevel, OrderStatus, Position, PositionDirection, Side, Ticker
from arb.utils.symbols import normalize_symbol, split_symbol

RestTransport = Callable[[dict[str, Any]], Awaitable[Any]]


def _missing_transport(_: dict[str, Any]) -> Awaitable[Any]:
    raise RuntimeError("a transport callable must be provided")


def utc_iso8601() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def utc_seconds() -> str:
    return str(int(datetime.now(tz=timezone.utc).timestamp()))


class OkxExchange(BaseExchangeClient):
    """OKX v5 REST adapter."""

    base_url = "https://www.okx.com"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        passphrase: str,
        *,
        transport: RestTransport | None = None,
    ) -> None:
        super().__init__("okx")
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
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
        ts = timestamp or utc_iso8601()
        request_path = f"{path}?{query}" if query else path
        prehash = f"{ts}{method.upper()}{request_path}{body}"
        digest = hmac.new(
            self.api_secret.encode("utf-8"),
            prehash.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        signature = base64.b64encode(digest).decode("utf-8")
        return {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
        }

    def build_login_args(self, timestamp: str | None = None) -> dict[str, str]:
        ts = timestamp or utc_seconds()
        digest = hmac.new(
            self.api_secret.encode("utf-8"),
            f"{ts}GET/users/self/verify".encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return {
            "apiKey": self.api_key,
            "passphrase": self.passphrase,
            "timestamp": ts,
            "sign": base64.b64encode(digest).decode("utf-8"),
        }

    def to_exchange_symbol(
        self,
        symbol: str,
        market_type: MarketType = MarketType.SPOT,
    ) -> str:
        base, quote = split_symbol(symbol)
        if market_type is MarketType.PERPETUAL:
            return f"{base}-{quote}-SWAP"
        return f"{base}-{quote}"

    def from_exchange_symbol(
        self,
        symbol: str,
        market_type: MarketType = MarketType.SPOT,
    ) -> str:
        raw = symbol.upper().replace("-SWAP", "")
        return normalize_symbol(raw.replace("-", "/"))

    async def fetch_ticker(self, symbol: str, market_type: MarketType) -> Ticker:
        payload = await self._request(
            "GET",
            "/api/v5/market/ticker",
            params={"instId": self.to_exchange_symbol(symbol, market_type)},
        )
        data = self._unwrap(payload)
        bid = Decimal(str(data["bidPx"]))
        ask = Decimal(str(data["askPx"]))
        return Ticker(
            exchange=self.name,
            symbol=self.from_exchange_symbol(str(data["instId"]), market_type),
            market_type=market_type,
            bid=bid,
            ask=ask,
            last=Decimal(str(data["last"])),
        )

    async def fetch_orderbook(
        self,
        symbol: str,
        market_type: MarketType,
        limit: int = 20,
    ) -> OrderBook:
        payload = await self._request(
            "GET",
            "/api/v5/market/books",
            params={"instId": self.to_exchange_symbol(symbol, market_type), "sz": str(limit)},
        )
        data = self._unwrap(payload)
        return OrderBook(
            exchange=self.name,
            symbol=self.from_exchange_symbol(str(data["instId"]), market_type),
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
            "/api/v5/public/funding-rate",
            params={"instId": self.to_exchange_symbol(symbol, MarketType.PERPETUAL)},
        )
        data = self._unwrap(payload)
        return FundingRate(
            exchange=self.name,
            symbol=self.from_exchange_symbol(str(data["instId"]), MarketType.PERPETUAL),
            rate=Decimal(str(data["fundingRate"])),
            predicted_rate=Decimal(str(data.get("nextFundingRate", data["fundingRate"]))),
            next_funding_time=datetime.fromtimestamp(int(data["nextFundingTime"]) / 1000, tz=timezone.utc),
        )

    async def fetch_balances(self) -> Mapping[str, Decimal]:
        payload = await self._request(
            "GET",
            "/api/v5/account/balance",
            params={},
            signed=True,
        )
        account = self._unwrap(payload)
        return {
            item["ccy"]: Decimal(str(item["cashBal"]))
            for item in account.get("details", [])
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
        inst_id = self.to_exchange_symbol(symbol, market_type)
        body = {
            "instId": inst_id,
            "tdMode": "cash" if market_type is MarketType.SPOT else "cross",
            "side": side.lower(),
            "ordType": "limit" if price is not None else "market",
            "sz": format(quantity, "f"),
        }
        if price is not None:
            body["px"] = format(price, "f")
        if market_type is MarketType.PERPETUAL and reduce_only:
            body["reduceOnly"] = "true"
        payload = await self._request(
            "POST",
            "/api/v5/trade/order",
            body=body,
            signed=True,
        )
        data = self._unwrap(payload)
        return Order(
            exchange=self.name,
            symbol=symbol,
            market_type=market_type,
            side=Side(side.lower()),
            quantity=quantity,
            price=price,
            status=OrderStatus.NEW,
            order_id=str(data.get("ordId", "")),
        )

    async def cancel_order(
        self,
        order_id: str,
        symbol: str,
        market_type: MarketType,
    ) -> Order:
        body = {
            "instId": self.to_exchange_symbol(symbol, market_type),
            "ordId": order_id,
        }
        await self._request(
            "POST",
            "/api/v5/trade/cancel-order",
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
        payload = await self._request(
            "GET",
            "/api/v5/trade/order",
            params={
                "instId": self.to_exchange_symbol(symbol, market_type),
                "ordId": order_id,
            },
            signed=True,
        )
        return self._parse_order(self._unwrap(payload), market_type)

    async def fetch_open_orders(
        self,
        symbol: str | None,
        market_type: MarketType,
    ) -> list[Order]:
        params: dict[str, Any] = {"instType": "SPOT" if market_type is MarketType.SPOT else "SWAP"}
        if symbol is not None:
            params["instId"] = self.to_exchange_symbol(symbol, market_type)
        payload = await self._request(
            "GET",
            "/api/v5/trade/orders-pending",
            params=params,
            signed=True,
        )
        return [self._parse_order(item, market_type) for item in payload.get("data", [])]

    async def fetch_positions(
        self,
        market_type: MarketType = MarketType.PERPETUAL,
        *,
        symbol: str | None = None,
    ) -> list[Position]:
        if market_type is MarketType.SPOT:
            return []
        params: dict[str, Any] = {"instType": "SWAP"}
        if symbol is not None:
            params["instId"] = self.to_exchange_symbol(symbol, market_type)
        payload = await self._request(
            "GET",
            "/api/v5/account/positions",
            params=params,
            signed=True,
        )
        return [position for item in payload.get("data", []) if (position := self._parse_position(item)) is not None]

    async def fetch_fills(
        self,
        order_id: str,
        symbol: str,
        market_type: MarketType,
    ) -> list[Fill]:
        payload = await self._request(
            "GET",
            "/api/v5/trade/fills",
            params={
                "instType": "SPOT" if market_type is MarketType.SPOT else "SWAP",
                "instId": self.to_exchange_symbol(symbol, market_type),
                "ordId": order_id,
            },
            signed=True,
        )
        return [self._parse_fill(item, market_type) for item in payload.get("data", [])]

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
            headers = dict(
                self.sign_request(
                    method,
                    path,
                    query=query,
                    body=body_text,
                )
            )
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

    @staticmethod
    def _unwrap(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        data = payload.get("data", [])
        if not data:
            return {}
        return data[0]

    def _parse_order(self, payload: Mapping[str, Any], market_type: MarketType) -> Order:
        status_map = {
            "live": OrderStatus.NEW,
            "partially_filled": OrderStatus.PARTIALLY_FILLED,
            "filled": OrderStatus.FILLED,
            "canceled": OrderStatus.CANCELED,
            "mmp_canceled": OrderStatus.CANCELED,
            "effective": OrderStatus.FILLED,
        }
        return Order(
            exchange=self.name,
            symbol=self.from_exchange_symbol(str(payload["instId"]), market_type),
            market_type=market_type,
            side=Side(str(payload.get("side", "buy")).lower()),
            quantity=Decimal(str(payload.get("sz", "0"))),
            price=Decimal(str(payload["px"])) if payload.get("px") not in (None, "") else None,
            status=status_map.get(str(payload.get("state", "live")).lower(), OrderStatus.NEW),
            order_id=str(payload.get("ordId", "")),
            client_order_id=str(payload["clOrdId"]) if payload.get("clOrdId") else None,
            filled_quantity=Decimal(str(payload.get("accFillSz", "0"))),
            average_price=Decimal(str(payload["avgPx"])) if payload.get("avgPx") not in (None, "", "0") else None,
            reduce_only=str(payload.get("reduceOnly", "false")).lower() == "true",
            raw_status=str(payload.get("state", "live")),
        )

    def _parse_position(self, payload: Mapping[str, Any]) -> Position | None:
        raw_quantity = Decimal(str(payload.get("pos", "0")))
        if raw_quantity == 0:
            return None
        pos_side = str(payload.get("posSide", "")).lower()
        direction = PositionDirection.LONG if raw_quantity > 0 or pos_side == "long" else PositionDirection.SHORT
        return Position(
            exchange=self.name,
            symbol=self.from_exchange_symbol(str(payload["instId"]), MarketType.PERPETUAL),
            market_type=MarketType.PERPETUAL,
            direction=direction,
            quantity=abs(raw_quantity),
            entry_price=Decimal(str(payload.get("avgPx", "0"))),
            mark_price=Decimal(str(payload.get("markPx", "0"))),
            unrealized_pnl=Decimal(str(payload.get("upl", "0"))),
            liquidation_price=Decimal(str(payload["liqPx"])) if payload.get("liqPx") not in (None, "", "0") else None,
            leverage=Decimal(str(payload["lever"])) if payload.get("lever") not in (None, "") else None,
            margin_mode=str(payload["mgnMode"]) if payload.get("mgnMode") else None,
            position_id=str(payload["posId"]) if payload.get("posId") else None,
        )

    def _parse_fill(self, payload: Mapping[str, Any], market_type: MarketType) -> Fill:
        return Fill(
            exchange=self.name,
            symbol=self.from_exchange_symbol(str(payload["instId"]), market_type),
            market_type=market_type,
            side=Side(str(payload.get("side", "buy")).lower()),
            quantity=Decimal(str(payload.get("fillSz", "0"))),
            price=Decimal(str(payload.get("fillPx", "0"))),
            order_id=str(payload.get("ordId", "")),
            fill_id=str(payload.get("tradeId", payload.get("fillIdxPx", ""))),
            fee=Decimal(str(payload.get("fee", "0"))),
            fee_asset=str(payload["feeCcy"]) if payload.get("feeCcy") else None,
            liquidity=str(payload["execType"]).lower() if payload.get("execType") else None,
            ts=datetime.fromtimestamp(int(payload.get("ts", "0")) / 1000, tz=timezone.utc),
        )
