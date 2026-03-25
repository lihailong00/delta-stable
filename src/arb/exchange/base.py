"""Base exchange abstractions."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Mapping
from decimal import Decimal
from urllib.parse import urlencode

from arb.models import Fill, FundingRate, MarketType, Order, OrderBook, Position, Ticker
from arb.net.schemas import HttpRequest
from arb.schemas.base import SerializableValue


class BaseExchangeClient(ABC):
    """Unified async REST interface for supported exchanges."""

    name: str

    def __init__(self, name: str) -> None:
        self.name = name

    @abstractmethod
    def sign_request(
        self,
        method: str,
        path: str,
        *,
        query: str = "",
        body: str = "",
        timestamp: str | None = None,
    ) -> Mapping[str, str]:
        """Return auth headers for a REST request."""

    @abstractmethod
    def to_exchange_symbol(
        self,
        symbol: str,
        market_type: MarketType = MarketType.SPOT,
    ) -> str:
        """Convert a normalized symbol into an exchange-specific one."""

    @abstractmethod
    def from_exchange_symbol(
        self,
        symbol: str,
        market_type: MarketType = MarketType.SPOT,
    ) -> str:
        """Convert an exchange-specific symbol into a normalized one."""

    @abstractmethod
    async def fetch_ticker(self, symbol: str, market_type: MarketType) -> Ticker:
        """Fetch ticker information for a symbol."""

    @abstractmethod
    async def fetch_orderbook(
        self, symbol: str, market_type: MarketType, limit: int = 20
    ) -> OrderBook:
        """Fetch order book data."""

    @abstractmethod
    async def fetch_funding_rate(self, symbol: str) -> FundingRate:
        """Fetch the current or predicted funding rate."""

    @abstractmethod
    async def fetch_balances(self) -> Mapping[str, Decimal]:
        """Fetch account balances keyed by asset."""

    @abstractmethod
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
        """Submit an order."""

    @abstractmethod
    async def cancel_order(
        self,
        order_id: str,
        symbol: str,
        market_type: MarketType,
    ) -> Order:
        """Cancel an order and return the latest order state."""

    @abstractmethod
    async def fetch_order(
        self,
        order_id: str,
        symbol: str,
        market_type: MarketType,
    ) -> Order:
        """Fetch the latest state for a specific order."""

    @abstractmethod
    async def fetch_open_orders(
        self,
        symbol: str | None,
        market_type: MarketType,
    ) -> list[Order]:
        """Fetch currently open orders, optionally scoped to one symbol."""

    @abstractmethod
    async def fetch_positions(
        self,
        market_type: MarketType = MarketType.PERPETUAL,
        *,
        symbol: str | None = None,
    ) -> list[Position]:
        """Fetch current positions, optionally scoped to one symbol."""

    @abstractmethod
    async def fetch_fills(
        self,
        order_id: str,
        symbol: str,
        market_type: MarketType,
    ) -> list[Fill]:
        """Fetch fills for a specific order."""

    async def fetch_many_tickers(
        self, symbols: list[str], market_type: MarketType
    ) -> dict[str, Ticker]:
        """Convenience helper for serial ticker polling."""

        result: dict[str, Ticker] = {}
        for symbol in symbols:
            result[symbol] = await self.fetch_ticker(symbol, market_type)
        return result

    def supports_market_type(self, market_type: MarketType) -> bool:
        """Allow subclasses to narrow supported market types."""

        return market_type in {MarketType.SPOT, MarketType.PERPETUAL}

    def build_request(
        self,
        method: str,
        path: str,
        *,
        query: str = "",
        body: str = "",
        timestamp: str | None = None,
    ) -> HttpRequest:
        """Build a transport-ready REST request description."""

        return HttpRequest(
            method=method.upper(),
            url=path,
            path=path,
            body_text=body,
            headers=dict(
                self.sign_request(
                    method.upper(),
                    path,
                    query=query,
                    body=body,
                    timestamp=timestamp,
                )
            ),
        )

    def build_json_request(
        self,
        method: str,
        path: str,
        *,
        base_url: str,
        params: Mapping[str, SerializableValue] | None = None,
        body: Mapping[str, SerializableValue] | None = None,
        headers: Mapping[str, str] | None = None,
        signed: bool = False,
    ) -> HttpRequest:
        """Build a JSON REST request with optional signed auth headers."""

        request_params = dict(params or {})
        query = urlencode({key: str(value) for key, value in request_params.items()})
        request_body = dict(body or {})
        body_text = json.dumps(request_body, separators=(",", ":")) if body is not None else ""
        request_headers = dict(headers or {})
        if signed:
            request_headers.update(self.sign_request(method, path, query=query, body=body_text))
        return HttpRequest(
            method=method,
            url=f"{base_url}{path}",
            path=path,
            params=request_params,
            json_body=request_body,
            body_text=body_text,
            headers=request_headers,
            signed=signed,
        )
