"""Shared network boundary schemas."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import Field, computed_field

from arb.schemas.base import ArbFrozenModel, SerializableValue

type JsonObject = dict[str, SerializableValue]
type JsonArray = list[SerializableValue]
type JsonValue = SerializableValue


class HttpRequest(ArbFrozenModel):
    """Normalized HTTP transport payload."""

    method: str
    url: str
    path: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    params: dict[str, SerializableValue] = Field(default_factory=dict)
    json_body: JsonObject | JsonArray | None = Field(default=None, alias="json")
    body_text: str | None = None
    timeout: float | None = None
    market_type: str | None = None
    signed: bool = False

    @computed_field
    @property
    def body(self) -> JsonObject | JsonArray | None:
        return self.json_body


def coerce_http_request(payload: HttpRequest | Mapping[str, SerializableValue]) -> HttpRequest:
    """Accept either a transport model or a legacy request mapping."""

    if isinstance(payload, HttpRequest):
        return payload
    candidate = dict(payload)
    if "body" in candidate and "json" not in candidate:
        candidate["json"] = candidate.pop("body")
    return HttpRequest.model_validate(candidate)


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
