"""Runtime protocols for live exchange orchestration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from arb.market.schemas import MarketSnapshot
from arb.models import MarketType
from arb.schemas.base import SerializableValue


@runtime_checkable
class SnapshotRuntimeProtocol(Protocol):
    """Runtime surface area required by realtime snapshot orchestration."""

    async def public_ping(self) -> bool:
        """Validate that the exchange public API is reachable."""

    async def fetch_public_snapshot(
        self,
        symbol: str,
        market_type: MarketType,
    ) -> MarketSnapshot:
        """Fetch a normalized market snapshot for a symbol."""


@runtime_checkable
class SmokeRuntimeProtocol(Protocol):
    """Runtime surface area required by smoke and private credential checks."""

    async def public_ping(self) -> bool:
        """Validate that the exchange public API is reachable."""

    async def validate_private_access(self) -> dict[str, str]:
        """Validate that private API credentials can read account state."""


@runtime_checkable
class LiveRuntimeProtocol(SnapshotRuntimeProtocol, SmokeRuntimeProtocol, Protocol):
    """Full runtime surface area used by both orchestration and smoke layers."""


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
    ) -> Mapping[str, SerializableValue]:
        """Build the raw subscription payload for a public channel."""
