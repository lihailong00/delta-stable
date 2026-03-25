"""Shared workflow components for routing and venue lookup."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Generic, Protocol, TypeVar

from arb.execution.router import ExecutionRouter, RouteDecision


@dataclass(slots=True, frozen=True)
class RoutePlanningRequest:
    """Inputs required to pick an execution route for a workflow attempt."""

    preferred_exchange: str
    urgent: bool
    maker_fee_rate: Decimal
    taker_fee_rate: Decimal
    spread_bps: Decimal
    fallback_exchange: str | None = None
    exchange_available: bool = True


class WorkflowRoutePlanner(Protocol):
    """Interface for workflow-level route planning."""

    def plan(self, request: RoutePlanningRequest) -> RouteDecision:
        """Return the execution route for the given workflow request."""


class DefaultWorkflowRoutePlanner:
    """Default route planner backed by the shared execution router."""

    def __init__(self, router: ExecutionRouter | None = None) -> None:
        self.router = router or ExecutionRouter()

    def plan(self, request: RoutePlanningRequest) -> RouteDecision:
        return self.router.route(
            preferred_exchange=request.preferred_exchange,
            fallback_exchange=request.fallback_exchange,
            exchange_available=request.exchange_available,
            urgent=request.urgent,
            maker_fee_rate=request.maker_fee_rate,
            taker_fee_rate=request.taker_fee_rate,
            spread_bps=request.spread_bps,
        )


VenueT = TypeVar("VenueT")


class VenueResolver(Protocol[VenueT]):
    """Interface for resolving a venue client bundle from a route exchange."""

    def resolve(self, venue_clients: Mapping[str, VenueT], exchange: str) -> VenueT | None:
        """Return the venue bundle that should handle the routed exchange."""


class DefaultVenueResolver(Generic[VenueT]):
    """Default venue lookup that reads directly from the venue mapping."""

    def resolve(self, venue_clients: Mapping[str, VenueT], exchange: str) -> VenueT | None:
        return venue_clients.get(exchange)
