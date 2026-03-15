"""Base exchange abstractions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from arb.models import FundingRate, MarketType, Order, OrderBook, Ticker


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
    ) -> dict[str, Any]:
        """Build a transport-ready REST request description."""

        return {
            "method": method.upper(),
            "path": path,
            "query": query,
            "body": body,
            "headers": dict(
                self.sign_request(
                    method.upper(),
                    path,
                    query=query,
                    body=body,
                    timestamp=timestamp,
                )
            ),
        }
