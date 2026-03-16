"""HTX REST adapter."""

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


def utc_timestamp() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


class HtxExchange(BaseExchangeClient):
    """HTX spot + USDT swap REST adapter."""

    spot_base_url = "https://api.huobi.pro"
    swap_base_url = "https://api.hbdm.com"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        leverage: int = 5,
        transport: RestTransport | None = None,
    ) -> None:
        super().__init__("htx")
        self.api_key = api_key
        self.api_secret = api_secret
        self.leverage = leverage
        self._transport = transport or _missing_transport
        self._spot_account_id: str | None = None

    def sign_request(
        self,
        method: str,
        path: str,
        *,
        host: str = "api.huobi.pro",
        params: Mapping[str, Any] | None = None,
        timestamp: str | None = None,
    ) -> Mapping[str, str]:
        base_params = {
            "AccessKeyId": self.api_key,
            "SignatureMethod": "HmacSHA256",
            "SignatureVersion": "2",
            "Timestamp": timestamp or utc_timestamp(),
        }
        merged = {**base_params, **{key: str(value) for key, value in (params or {}).items()}}
        encoded = urlencode(sorted(merged.items()))
        payload = "\n".join([method.upper(), host.lower(), path, encoded])
        digest = hmac.new(
            self.api_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        merged["Signature"] = base64.b64encode(digest).decode("utf-8")
        return {key: str(value) for key, value in merged.items()}

    def build_ws_auth_params(
        self,
        *,
        host: str = "api.huobi.pro",
        path: str = "/ws/v2",
        timestamp: str | None = None,
    ) -> Mapping[str, str]:
        ts = timestamp or utc_timestamp()
        params = {
            "accessKey": self.api_key,
            "signatureMethod": "HmacSHA256",
            "signatureVersion": "2.1",
            "timestamp": ts,
        }
        encoded = urlencode(sorted(params.items()))
        payload = "\n".join(["GET", host.lower(), path, encoded])
        digest = hmac.new(
            self.api_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return {
            **params,
            "authType": "api",
            "signature": base64.b64encode(digest).decode("utf-8"),
        }

    def to_exchange_symbol(
        self,
        symbol: str,
        market_type: MarketType = MarketType.SPOT,
    ) -> str:
        base, quote = split_symbol(symbol)
        if market_type is MarketType.PERPETUAL:
            return f"{base}-{quote}"
        return f"{base}{quote}".lower()

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
                "/market/detail/merged",
                params={"symbol": self.to_exchange_symbol(symbol, market_type)},
                base_url=self.spot_base_url,
            )
        else:
            payload = await self._request(
                "GET",
                "/linear-swap-ex/market/detail/merged",
                params={"contract_code": self.to_exchange_symbol(symbol, market_type)},
                base_url=self.swap_base_url,
            )
        tick = payload["tick"]
        bid = Decimal(str(tick["bid"][0]))
        ask = Decimal(str(tick["ask"][0]))
        last = Decimal(str(tick.get("close", tick["bid"][0])))
        return Ticker(
            exchange=self.name,
            symbol=symbol,
            market_type=market_type,
            bid=bid,
            ask=ask,
            last=last,
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
                "/market/depth",
                params={"symbol": self.to_exchange_symbol(symbol, market_type), "type": "step0"},
                base_url=self.spot_base_url,
            )
        else:
            payload = await self._request(
                "GET",
                "/linear-swap-ex/market/depth",
                params={"contract_code": self.to_exchange_symbol(symbol, market_type), "type": "step0"},
                base_url=self.swap_base_url,
            )
        tick = payload["tick"]
        return OrderBook(
            exchange=self.name,
            symbol=symbol,
            market_type=market_type,
            bids=tuple(
                OrderBookLevel(price=Decimal(str(level[0])), size=Decimal(str(level[1])))
                for level in tick.get("bids", [])[:limit]
            ),
            asks=tuple(
                OrderBookLevel(price=Decimal(str(level[0])), size=Decimal(str(level[1])))
                for level in tick.get("asks", [])[:limit]
            ),
        )

    async def fetch_funding_rate(self, symbol: str) -> FundingRate:
        payload = await self._request(
            "GET",
            "/linear-swap-api/v1/swap_funding_rate",
            params={"contract_code": self.to_exchange_symbol(symbol, MarketType.PERPETUAL)},
            base_url=self.swap_base_url,
        )
        data = payload["data"]
        return FundingRate(
            exchange=self.name,
            symbol=self.from_exchange_symbol(str(data["contract_code"]), MarketType.PERPETUAL),
            rate=Decimal(str(data["funding_rate"])),
            predicted_rate=Decimal(str(data.get("estimated_rate", data["funding_rate"]))),
            next_funding_time=datetime.fromtimestamp(int(data["next_funding_time"]) / 1000, tz=timezone.utc),
        )

    async def fetch_balances(self) -> Mapping[str, Decimal]:
        account_id = await self._ensure_spot_account_id()
        payload = await self._request(
            "GET",
            f"/v1/account/accounts/{account_id}/balance",
            signed=True,
            base_url=self.spot_base_url,
            host="api.huobi.pro",
        )
        balances: dict[str, Decimal] = {}
        for item in payload["data"].get("list", []):
            currency = str(item["currency"]).upper()
            balances[currency] = balances.get(currency, Decimal("0")) + Decimal(str(item["balance"]))
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
            account_id = await self._ensure_spot_account_id()
            order_type = f"{side.lower()}-{'limit' if price is not None else 'market'}"
            body: dict[str, Any] = {
                "account-id": account_id,
                "symbol": self.to_exchange_symbol(symbol, market_type),
                "type": order_type,
                "amount": format(quantity, "f"),
            }
            if price is not None:
                body["price"] = format(price, "f")
            payload = await self._request(
                "POST",
                "/v1/order/orders/place",
                body=body,
                signed=True,
                base_url=self.spot_base_url,
                host="api.huobi.pro",
            )
            order_id = payload["data"]
        else:
            direction, offset = self._swap_direction_offset(side, reduce_only)
            body = {
                "contract_code": self.to_exchange_symbol(symbol, market_type),
                "direction": direction,
                "offset": offset,
                "lever_rate": self.leverage,
                "volume": int(quantity),
                "order_price_type": "limit" if price is not None else "optimal_20",
            }
            if price is not None:
                body["price"] = format(price, "f")
            payload = await self._request(
                "POST",
                "/linear-swap-api/v1/swap_order",
                body=body,
                signed=True,
                base_url=self.swap_base_url,
                host="api.hbdm.com",
            )
            order_id = payload["data"]["order_id_str"]
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
            await self._request(
                "POST",
                f"/v1/order/orders/{order_id}/submitcancel",
                signed=True,
                base_url=self.spot_base_url,
                host="api.huobi.pro",
            )
        else:
            body = {
                "contract_code": self.to_exchange_symbol(symbol, market_type),
                "order_id": order_id,
            }
            await self._request(
                "POST",
                "/linear-swap-api/v1/swap_cancel",
                body=body,
                signed=True,
                base_url=self.swap_base_url,
                host="api.hbdm.com",
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

    async def _ensure_spot_account_id(self) -> str:
        if self._spot_account_id is not None:
            return self._spot_account_id
        payload = await self._request(
            "GET",
            "/v1/account/accounts",
            signed=True,
            base_url=self.spot_base_url,
            host="api.huobi.pro",
        )
        accounts = payload.get("data", [])
        if not accounts:
            raise RuntimeError("HTX returned no accounts")
        spot = next((account for account in accounts if account.get("type") == "spot"), accounts[0])
        self._spot_account_id = str(spot["id"])
        return self._spot_account_id

    def _swap_direction_offset(self, side: str, reduce_only: bool) -> tuple[str, str]:
        normalized = side.lower()
        if normalized not in {"buy", "sell"}:
            raise ValueError(f"unsupported side: {side}")
        if reduce_only:
            return ("buy", "close") if normalized == "buy" else ("sell", "close")
        return normalized, "open"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
        signed: bool = False,
        base_url: str,
        host: str | None = None,
    ) -> Any:
        request_params = {key: str(value) for key, value in (params or {}).items()}
        if signed:
            request_params = dict(
                self.sign_request(
                    method,
                    path,
                    host=host or base_url.split("://", 1)[1],
                    params=request_params,
                )
            )
        body_text = json.dumps(body or {}, separators=(",", ":")) if body is not None else ""
        request = {
            "method": method,
            "url": f"{base_url}{path}",
            "path": path,
            "params": request_params,
            "query": urlencode(sorted(request_params.items())),
            "body": body or {},
            "body_text": body_text,
            "headers": {"Content-Type": "application/json"} if body is not None else {},
            "signed": signed,
        }
        payload = await self._transport(request)
        status = str(payload.get("status", "ok"))
        if status != "ok":
            raise RuntimeError(f"HTX request failed: {payload.get('err-code', payload.get('err-msg', status))}")
        return payload
