"""Control API schemas."""

from __future__ import annotations

from dataclasses import asdict, dataclass
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
class CommandRequest:
    action: str
    target: str
    requested_by: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class CommandResponse:
    accepted: bool
    command_id: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
