"""Runtime protocols for live exchange orchestration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from arb.models import MarketType


@runtime_checkable
class LiveRuntimeProtocol(Protocol):
    """Common surface area expected by orchestration and smoke layers."""

    async def public_ping(self) -> bool:
        """Validate that the exchange public API is reachable."""

    async def validate_private_access(self) -> dict[str, Any]:
        """Validate that private API credentials can read account state."""

    async def fetch_public_snapshot(
        self,
        symbol: str,
        market_type: MarketType,
    ) -> dict[str, Any]:
        """Fetch a normalized market snapshot for a symbol."""


@runtime_checkable
class PrivateWsMessageBuilder(Protocol):
    """WS client surface required for private login/auth sessions."""

    endpoint: str


@runtime_checkable
class SubscribableWsClient(Protocol):
    """WS client surface required for public streaming helpers."""

    endpoint: str

    def build_subscribe_message(
        self,
        channel: str,
        *,
        symbol: str | None = None,
        market: str | None = None,
    ) -> Mapping[str, Any]:
        """Build the raw subscription payload for a public channel."""
