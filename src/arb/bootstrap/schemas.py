"""Bootstrap-facing schemas and handler contracts."""

from __future__ import annotations

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
    def from_object(cls, args: Mapping[str, SerializableValue] | object) -> "FundingArbCliArgs":
        return cls(
            exchange=_read_sequence_arg(args, "exchange"),
            symbol=_read_sequence_arg(args, "symbol"),
            market_type=str(_read_arg(args, "market_type", "perpetual")),
            iterations=int(_read_arg(args, "iterations", 1)),
        )


class FundingArbRunReport(ArbFrozenModel):
    iterations: int
    results: list[dict[str, SerializableValue]] = Field(default_factory=list)


type CliResult = CliParsedResult | FundingArbRunReport | ArbModel | SerializableValue
type CommandHandler = Callable[[Mapping[str, SerializableValue]], CliResult | Awaitable[CliResult]]
type CommandHandlerMap = Mapping[str, CommandHandler]


def cli_args_to_serializable(args: Mapping[str, object]) -> dict[str, SerializableValue]:
    """Convert CLI argument payloads into explicit serializable values."""

    serializable: dict[str, SerializableValue] = {}
    for key, value in args.items():
        serializable[key] = to_serializable(value)
    return serializable


def _read_arg(args: Mapping[str, SerializableValue] | object, key: str, default: object) -> object:
    if isinstance(args, Mapping):
        return args.get(key, default)
    return getattr(args, key, default)


def _read_sequence_arg(args: Mapping[str, SerializableValue] | object, key: str) -> tuple[str, ...]:
    value = _read_arg(args, key, ())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(str(item) for item in value)
    if value in (None, ""):
        return ()
    return (str(value),)


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
