"""Bootstrap-facing schemas and handler contracts."""

from __future__ import annotations

import argparse
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import cast

from pydantic import Field

from arb.schemas.base import ArbFrozenModel, ArbModel, SerializableValue


class CliParsedResult(ArbFrozenModel):
    command: str
    args: dict[str, SerializableValue]


class FundingArbCliArgs(ArbFrozenModel):
    exchange: tuple[str, ...]
    symbol: tuple[str, ...]
    market_type: str = "perpetual"
    iterations: int = 1

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> "FundingArbCliArgs":
        return cls(
            exchange=tuple(getattr(args, "exchange", ())),
            symbol=tuple(getattr(args, "symbol", ())),
            market_type=str(getattr(args, "market_type", "perpetual")),
            iterations=int(getattr(args, "iterations", 1)),
        )


class FundingArbRunReport(ArbFrozenModel):
    iterations: int
    results: list[dict[str, SerializableValue]] = Field(default_factory=list)


type CliResult = CliParsedResult | FundingArbRunReport | ArbModel | SerializableValue
type CommandHandler = Callable[[argparse.Namespace], CliResult | Awaitable[CliResult]]
type CommandHandlerMap = Mapping[str, CommandHandler]


def namespace_to_serializable(args: argparse.Namespace) -> dict[str, SerializableValue]:
    """Convert argparse namespaces into explicit serializable payloads."""

    serializable: dict[str, SerializableValue] = {}
    for key, value in vars(args).items():
        if isinstance(value, Sequence) and not isinstance(value, str):
            serializable[key] = [item for item in value]
        else:
            serializable[key] = value
    return serializable


def to_serializable(value: object) -> SerializableValue:
    """Recursively normalize runtime results into explicit serializable values."""

    if isinstance(value, ArbModel):
        return {key: to_serializable(item) for key, item in value.to_dict().items()}
    if is_dataclass(value) and not isinstance(value, type):
        return {key: to_serializable(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): to_serializable(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [to_serializable(item) for item in value]
    if isinstance(value, Enum):
        return cast(SerializableValue, value.value)
    return cast(SerializableValue, value)
