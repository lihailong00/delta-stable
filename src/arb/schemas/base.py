"""Shared Pydantic schema base classes."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict

type SerializableScalar = (
    str
    | int
    | float
    | bool
    | None
    | Decimal
    | datetime
    | date
    | time
    | timedelta
    | Enum
)
type SerializableValue = (
    SerializableScalar
    | list["SerializableValue"]
    | tuple["SerializableValue", ...]
    | dict[str, "SerializableValue"]
)


class ArbModel(BaseModel):
    """Base mutable model for explicit project schemas."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        validate_assignment=True,
    )

    def to_dict(self) -> dict[str, SerializableValue]:
        return self.model_dump(mode="python", by_alias=True)

    def __getitem__(self, item: str) -> SerializableValue:
        value = getattr(self, item, None)
        if callable(value) or (value is None and item in self.to_dict()):
            return self.to_dict()[item]
        if isinstance(value, Enum):
            return value.value
        return value

    def get(self, item: str, default: SerializableValue | None = None) -> SerializableValue | None:
        value = getattr(self, item, default)
        if callable(value) or (value is default and item in self.to_dict()):
            return self.to_dict().get(item, default)
        if isinstance(value, Enum):
            return value.value
        return value

    def keys(self) -> Iterator[str]:
        return iter(self.to_dict().keys())

    def values(self) -> Iterator[SerializableValue]:
        return iter(self.to_dict().values())

    def items(self) -> Iterator[tuple[str, SerializableValue]]:
        return iter(self.to_dict().items())


class ArbFrozenModel(ArbModel):
    """Base immutable model for domain objects."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        frozen=True,
    )
