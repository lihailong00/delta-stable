"""Gate.io REST adapter."""

from __future__ import annotations

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
from arb.models import FundingRate, MarketType, Order, OrderBook, OrderBookLevel, OrderStatus, Side, Ticker
from arb.utils.symbols import exchange_symbol, normalize_symbol

RestTransport = Callable[[dict[str, Any]], Awaitable[Any]]


def _missing_transport(_: dict[str, Any]) -> Awaitable[Any]:
    raise RuntimeError("a transport callable must be provided")


def _hash_body(body: str) -> str:
    return hashlib.sha512(body.encode("utf-8")).hexdigest()


class GateExchange(BaseExchangeClient):
    """Gate.io API v4 REST adapter."""

    base_url = "https://api.gateio.ws/api/v4"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        settle: str = "usdt",
        transport: RestTransport | None = None,
    ) -> None:
        super().__init__("gate")
        self.api_key = api_key
        self.api_secret = api_secret
        self.settle = settle
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
        ts = timestamp or str(int(time.time()))
        payload = "\n".join(
            [
                method.upper(),
                path,
                query,
                _hash_body(body),
                ts,
            ]
        )
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha512,
        ).hexdigest()
        return {
            "KEY": self.api_key,
            "SIGN": signature,
            "Timestamp": ts,
            "Content-Type": "application/json",
        }

    def to_exchange_symbol(
        self,
        symbol: str,
        market_type: MarketType = MarketType.SPOT,
    ) -> str:
        return exchange_symbol(symbol, delimiter="_")

    def from_exchange_symbol(
        self,
        symbol: str,
        market_type: MarketType = MarketType.SPOT,
    ) -> str:
        return normalize_symbol(symbol)

    async def fetch_ticker(self, symbol: str, market_type: MarketType) -> Ticker:
        if market_type is MarketType.SPOT:
            payload = await self._request(
                "GET",
                "/spot/tickers",
                params={"currency_pair": self.to_exchange_symbol(symbol)},
            )
            data = payload[0]
            bid = Decimal(str(data["highest_bid"]))
            ask = Decimal(str(data["lowest_ask"]))
            return Ticker(
                exchange=self.name,
                symbol=self.from_exchange_symbol(str(data["currency_pair"])),
                market_type=market_type,
                bid=bid,
                ask=ask,
                last=Decimal(str(data["last"])),
            )
        payload = await self._request(
            "GET",
            f"/futures/{self.settle}/tickers",
            params={"contract": self.to_exchange_symbol(symbol, market_type)},
        )
        data = payload[0]
        return Ticker(
            exchange=self.name,
            symbol=self.from_exchange_symbol(str(data["contract"]), market_type),
            market_type=market_type,
            bid=Decimal(str(data["highest_bid"])),
            ask=Decimal(str(data["lowest_ask"])),
            last=Decimal(str(data["last"])),
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
                "/spot/order_book",
                params={"currency_pair": self.to_exchange_symbol(symbol), "limit": str(limit)},
            )
            pair_key = "currency_pair"
        else:
            payload = await self._request(
                "GET",
                f"/futures/{self.settle}/order_book",
                params={"contract": self.to_exchange_symbol(symbol, market_type), "limit": str(limit)},
            )
            pair_key = "contract"
        bids_key = "bids"
        asks_key = "asks"
        return OrderBook(
            exchange=self.name,
            symbol=symbol,
            market_type=market_type,
            bids=tuple(
                OrderBookLevel(price=Decimal(str(level[0])), size=Decimal(str(level[1])))
                for level in payload.get(bids_key, [])
            ),
            asks=tuple(
                OrderBookLevel(price=Decimal(str(level[0])), size=Decimal(str(level[1])))
                for level in payload.get(asks_key, [])
            ),
        )

    async def fetch_funding_rate(self, symbol: str) -> FundingRate:
        payload = await self._request(
            "GET",
            f"/futures/{self.settle}/contracts/{self.to_exchange_symbol(symbol, MarketType.PERPETUAL)}",
        )
        return FundingRate(
            exchange=self.name,
            symbol=self.from_exchange_symbol(str(payload["name"]), MarketType.PERPETUAL),
            rate=Decimal(str(payload.get("funding_rate", payload.get("funding_rate_indicative", "0")))),
            predicted_rate=Decimal(str(payload.get("funding_rate_indicative", payload.get("funding_rate", "0")))),
            next_funding_time=datetime.fromtimestamp(int(payload["funding_next_apply"]) / 1000, tz=timezone.utc),
        )

    async def fetch_balances(self) -> Mapping[str, Decimal]:
        payload = await self._request("GET", "/spot/accounts", signed=True)
        return {
            item["currency"].upper(): Decimal(str(item["available"])) + Decimal(str(item.get("locked", "0")))
            for item in payload
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
        if market_type is MarketType.SPOT:
            body = {
                "currency_pair": self.to_exchange_symbol(symbol),
                "type": "limit" if price is not None else "market",
                "account": "spot",
                "side": side,
                "amount": format(quantity, "f"),
            }
            if price is not None:
                body["price"] = format(price, "f")
            payload = await self._request("POST", "/spot/orders", body=body, signed=True)
        else:
            body = {
                "contract": self.to_exchange_symbol(symbol, market_type),
                "size": str(int(quantity) if side.lower() == "buy" else -int(quantity)),
                "price": format(price, "f") if price is not None else "0",
                "tif": "gtc" if price is not None else "ioc",
                "reduce_only": reduce_only,
            }
            payload = await self._request(
                "POST",
                f"/futures/{self.settle}/orders",
                body=body,
                signed=True,
            )
        return Order(
            exchange=self.name,
            symbol=symbol,
            market_type=market_type,
            side=Side(side.lower()),
            quantity=quantity,
            price=price,
            status=OrderStatus.NEW,
            order_id=str(payload.get("id", "")),
        )

    async def cancel_order(
        self,
        order_id: str,
        symbol: str,
        market_type: MarketType,
    ) -> Order:
        if market_type is MarketType.SPOT:
            await self._request("DELETE", f"/spot/orders/{order_id}", signed=True)
        else:
            await self._request("DELETE", f"/futures/{self.settle}/orders/{order_id}", signed=True)
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
