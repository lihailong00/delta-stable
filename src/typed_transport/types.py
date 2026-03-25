"""Shared transport types and schemas."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Any, Protocol, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field, computed_field

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
type JsonObject = dict[str, JsonValue]
type JsonArray = list[JsonValue]

RequestModelT = TypeVar("RequestModelT", bound=BaseModel)


class SupportsModelDump(Protocol):
    def model_dump(self, *, mode: str = "python", by_alias: bool = False) -> dict[str, Any]:
        """Return a dict payload."""


class TransportModel(BaseModel):
    """Base mutable model for transport-facing schemas."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        validate_assignment=True,
    )

    def to_dict(self) -> JsonObject:
        return cast(JsonObject, self.model_dump(mode="python", by_alias=True))

    def __getitem__(self, item: str) -> JsonValue:
        return self.to_dict()[item]

    def get(self, item: str, default: JsonValue | None = None) -> JsonValue | None:
        return self.to_dict().get(item, default)

    def keys(self) -> Iterator[str]:
        return iter(self.to_dict().keys())

    def values(self) -> Iterator[JsonValue]:
        return iter(self.to_dict().values())

    def items(self) -> Iterator[tuple[str, JsonValue]]:
        return iter(self.to_dict().items())


class TransportFrozenModel(TransportModel):
    """Base immutable model for transport-facing schemas."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        frozen=True,
    )


class HttpRequest(TransportFrozenModel):
    """Normalized HTTP request payload."""

    method: str
    url: str
    path: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    params: dict[str, JsonValue] = Field(default_factory=dict)
    json_body: JsonObject | JsonArray | None = Field(default=None, alias="json")
    body_text: str | None = None
    timeout: float | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def body(self) -> JsonObject | JsonArray | None:
        return self.json_body


def _normalize_http_request_mapping(payload: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """Normalize legacy request keys before model validation."""

    candidate = dict(payload)
    if "body" in candidate and "json" not in candidate:
        candidate["json"] = candidate.pop("body")
    return candidate


def coerce_request_model(
    model_type: type[RequestModelT],
    payload: RequestModelT | Mapping[str, JsonValue],
) -> RequestModelT:
    """Accept a request model instance or validate a legacy request mapping."""

    if isinstance(payload, model_type):
        return payload
    return model_type.model_validate(_normalize_http_request_mapping(payload))


def coerce_http_request(payload: HttpRequest | Mapping[str, JsonValue]) -> HttpRequest:
    """Accept either a transport model or a legacy request mapping."""

    return coerce_request_model(HttpRequest, payload)


def expect_mapping(payload: JsonValue, *, context: str) -> JsonObject:
    """Require a JSON object response."""

    if not isinstance(payload, Mapping):
        raise TypeError(f"{context} expected mapping payload, got {type(payload).__name__}")
    return dict(payload)


def expect_list(payload: JsonValue, *, context: str) -> JsonArray:
    """Require a JSON array response."""

    if not isinstance(payload, list):
        raise TypeError(f"{context} expected list payload, got {type(payload).__name__}")
    return list(payload)


def serialize_message(message: object) -> JsonValue | str:
    """Convert a typed payload into a wire-safe JSON object or string."""

    if isinstance(message, str):
        return message
    if isinstance(message, TransportModel):
        return message.to_dict()
    if isinstance(message, Enum):
        return cast(JsonValue, message.value)
    if hasattr(message, "to_dict") and callable(getattr(message, "to_dict")):
        return cast(JsonObject, message.to_dict())
    if hasattr(message, "model_dump") and callable(getattr(message, "model_dump")):
        return cast(JsonObject, message.model_dump(mode="python", by_alias=True))
    if isinstance(message, Mapping):
        return {str(key): cast(JsonValue, value) for key, value in message.items()}
    if isinstance(message, (list, tuple)):
        return [cast(JsonValue, item) for item in message]
    raise TypeError(f"unsupported transport message type: {type(message).__name__}")
