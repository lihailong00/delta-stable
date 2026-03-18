"""Protocols for execution and workflow collaborators."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from decimal import Decimal
from typing import Protocol, TypeGuard, runtime_checkable

from arb.models import Fill, MarketType, Order


@runtime_checkable
class CreateOrderClient(Protocol):
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


@runtime_checkable
class CancelOrderClient(Protocol):
    async def cancel_order(
        self,
        order_id: str,
        symbol: str,
        market_type: MarketType,
    ) -> Order | None:
        """Cancel an existing order."""


@runtime_checkable
class FetchOrderClient(Protocol):
    async def fetch_order(
        self,
        order_id: str,
        symbol: str,
        market_type: MarketType,
    ) -> Order:
        """Fetch the latest order state."""


@runtime_checkable
class FetchFillsClient(Protocol):
    async def fetch_fills(
        self,
        order_id: str,
        symbol: str,
        market_type: MarketType,
    ) -> Iterable[Fill]:
        """Fetch fills associated with an order."""


@runtime_checkable
class OrderExecutionClient(CreateOrderClient, Protocol):
    """Minimum client surface needed for order submission."""


@runtime_checkable
class FullOrderClient(
    CreateOrderClient,
    CancelOrderClient,
    FetchOrderClient,
    FetchFillsClient,
    Protocol,
):
    """Complete exchange client surface used by workflows."""


type TrackableOrderClient = (
    CreateOrderClient
    | CancelOrderClient
    | FetchOrderClient
    | FetchFillsClient
)


type SleepFn = Callable[[float], Awaitable[None] | None]
type ClockFn = Callable[[], float]


def supports_cancel_order(client: object) -> TypeGuard[CancelOrderClient]:
    return isinstance(client, CancelOrderClient)


def supports_fetch_order(client: object) -> TypeGuard[FetchOrderClient]:
    return isinstance(client, FetchOrderClient)


def supports_fetch_fills(client: object) -> TypeGuard[FetchFillsClient]:
    return isinstance(client, FetchFillsClient)
