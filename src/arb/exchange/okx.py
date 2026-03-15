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
from arb.models import FundingRate, MarketType, Order, OrderBook, OrderBookLevel, OrderStatus, Side, Ticker
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
