"""Control API schemas."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class HealthResponse:
    status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class PositionResponse:
    exchange: str
    symbol: str
    market_type: str
    quantity: str
    direction: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class StrategyResponse:
    name: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class OrderResponse:
    exchange: str
    symbol: str
    market_type: str
    order_id: str
    status: str
    filled_quantity: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class WorkflowResponse:
    workflow_id: str
    workflow_type: str
    exchange: str
    symbol: str
    status: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class CommandRequest:
    action: str
    target: str
    requested_by: str
    require_confirmation: bool = False
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class CommandResponse:
    accepted: bool
    command_id: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
