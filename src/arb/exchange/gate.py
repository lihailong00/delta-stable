"""Gate.io REST adapter."""

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

RestTransport = Callable[[HttpRequest], Awaitable[JsonValue]]


def _missing_transport(_: HttpRequest) -> Awaitable[JsonValue]:
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

    async def fetch_order(
        self,
        order_id: str,
        symbol: str,
        market_type: MarketType,
    ) -> Order:
        if market_type is MarketType.SPOT:
            payload = await self._request(
                "GET",
                f"/spot/orders/{order_id}",
                params={"currency_pair": self.to_exchange_symbol(symbol, market_type)},
                signed=True,
            )
        else:
            payload = await self._request(
                "GET",
                f"/futures/{self.settle}/orders/{order_id}",
                params={"contract": self.to_exchange_symbol(symbol, market_type)},
                signed=True,
            )
        return self._parse_order(payload, symbol, market_type)

    async def fetch_open_orders(
        self,
        symbol: str | None,
        market_type: MarketType,
    ) -> list[Order]:
        if market_type is MarketType.SPOT:
            params: dict[str, SerializableValue] = {"status": "open"}
            if symbol is not None:
                params["currency_pair"] = self.to_exchange_symbol(symbol, market_type)
            payload = await self._request("GET", "/spot/orders", params=params, signed=True)
        else:
            params = {"status": "open"}
            if symbol is not None:
                params["contract"] = self.to_exchange_symbol(symbol, market_type)
            payload = await self._request("GET", f"/futures/{self.settle}/orders", params=params, signed=True)
        target_symbol = symbol or ""
        return [self._parse_order(item, target_symbol, market_type) for item in payload]

    async def fetch_positions(
        self,
        market_type: MarketType = MarketType.PERPETUAL,
        *,
        symbol: str | None = None,
    ) -> list[Position]:
        if market_type is MarketType.SPOT:
            return []
        params: dict[str, SerializableValue] = {}
        if symbol is not None:
            params["contract"] = self.to_exchange_symbol(symbol, market_type)
        payload = await self._request(
            "GET",
            f"/futures/{self.settle}/positions",
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
        if market_type is MarketType.SPOT:
            payload = await self._request(
                "GET",
                "/spot/my_trades",
                params={"currency_pair": self.to_exchange_symbol(symbol), "order_id": order_id},
                signed=True,
            )
        else:
            payload = await self._request(
                "GET",
                f"/futures/{self.settle}/my_trades",
                params={"contract": self.to_exchange_symbol(symbol, market_type), "order": order_id},
                signed=True,
            )
        return [self._parse_fill(item, symbol, market_type) for item in payload]

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

    def _parse_order(self, payload: Mapping[str, object], symbol: str, market_type: MarketType) -> Order:
        if market_type is MarketType.SPOT:
            status_key = str(payload.get("status", "open")).lower()
            status = {
                "open": OrderStatus.NEW,
                "closed": OrderStatus.FILLED,
                "cancelled": OrderStatus.CANCELED,
                "finished": OrderStatus.FILLED,
            }.get(status_key, OrderStatus.NEW)
            quantity = Decimal(str(payload.get("amount", "0")))
            filled_quantity = Decimal(str(payload.get("filled_amount", payload.get("left", "0"))))
            if "filled_total" in payload and payload.get("avg_deal_price") not in (None, "", "0"):
                avg_price = Decimal(str(payload["avg_deal_price"]))
            else:
                avg_price = None
            side = Side(str(payload.get("side", "buy")).lower())
            parsed_symbol = self.from_exchange_symbol(str(payload.get("currency_pair", self.to_exchange_symbol(symbol))), market_type)
        else:
            finish_as = str(payload.get("finish_as", "open")).lower()
            status = {
                "open": OrderStatus.NEW,
                "filled": OrderStatus.FILLED,
                "cancelled": OrderStatus.CANCELED,
                "liquidated": OrderStatus.EXPIRED,
            }.get(finish_as, OrderStatus.NEW)
            raw_size = Decimal(str(payload.get("size", "0")))
            quantity = abs(raw_size)
            if payload.get("left") is not None:
                left_quantity = Decimal(str(payload.get("left", "0")))
                filled_quantity = abs(raw_size) - abs(left_quantity)
            else:
                filled_quantity = Decimal(str(payload.get("fill_size", quantity)))
            avg_price = Decimal(str(payload["fill_price"])) if payload.get("fill_price") not in (None, "", "0") else None
            side = Side.BUY if raw_size > 0 else Side.SELL
            parsed_symbol = self.from_exchange_symbol(str(payload.get("contract", self.to_exchange_symbol(symbol, market_type))), market_type)
        return Order(
            exchange=self.name,
            symbol=parsed_symbol,
            market_type=market_type,
            side=side,
            quantity=quantity,
            price=Decimal(str(payload["price"])) if payload.get("price") not in (None, "", "0") else None,
            status=status,
            order_id=str(payload.get("id", "")),
            client_order_id=str(payload["text"]) if payload.get("text") else None,
            filled_quantity=filled_quantity,
            average_price=avg_price,
            reduce_only=bool(payload.get("reduce_only", False)),
            raw_status=str(payload.get("status", payload.get("finish_as", "open"))),
        )

    def _parse_position(self, payload: Mapping[str, object]) -> Position | None:
        raw_size = Decimal(str(payload.get("size", "0")))
        if raw_size == 0:
            return None
        direction = PositionDirection.LONG if raw_size > 0 else PositionDirection.SHORT
        return Position(
            exchange=self.name,
            symbol=self.from_exchange_symbol(str(payload.get("contract", payload.get("name", ""))), MarketType.PERPETUAL),
            market_type=MarketType.PERPETUAL,
            direction=direction,
            quantity=abs(raw_size),
            entry_price=Decimal(str(payload.get("entry_price", payload.get("avg_entry_price", "0")))),
            mark_price=Decimal(str(payload.get("mark_price", payload.get("markPrice", "0")))),
            unrealized_pnl=Decimal(str(payload.get("unrealised_pnl", payload.get("pnl", "0")))),
            liquidation_price=Decimal(str(payload["liq_price"])) if payload.get("liq_price") not in (None, "", "0") else None,
            leverage=Decimal(str(payload["leverage"])) if payload.get("leverage") not in (None, "", "0") else None,
            margin_mode=str(payload["mode"]) if payload.get("mode") else None,
        )

    def _parse_fill(self, payload: Mapping[str, object], symbol: str, market_type: MarketType) -> Fill:
        side = payload.get("side")
        if side is None:
            raw_size = Decimal(str(payload.get("size", "0")))
            side = "buy" if raw_size > 0 else "sell"
        liquidity = str(payload["role"]).lower() if payload.get("role") else None
        ts_value = payload.get("create_time_ms", payload.get("create_time", int(time.time())))
        if isinstance(ts_value, str) and ts_value.isdigit():
            timestamp = datetime.fromtimestamp(int(ts_value) / (1000 if len(ts_value) > 10 else 1), tz=timezone.utc)
        else:
            timestamp = datetime.fromtimestamp(int(ts_value) / (1000 if int(ts_value) > 10**10 else 1), tz=timezone.utc)
        quantity = Decimal(str(payload.get("amount", payload.get("size", "0"))))
        return Fill(
            exchange=self.name,
            symbol=symbol,
            market_type=market_type,
            side=Side(str(side).lower()),
            quantity=abs(quantity),
            price=Decimal(str(payload.get("price", payload.get("fill_price", "0")))),
            order_id=str(payload.get("order_id", payload.get("id", ""))),
            fill_id=str(payload.get("id", payload.get("trade_id", ""))),
            fee=Decimal(str(payload.get("fee", "0"))),
            fee_asset=str(payload["fee_currency"]) if payload.get("fee_currency") else None,
            liquidity=liquidity,
            ts=timestamp,
        )
