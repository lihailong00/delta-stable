"""Compatibility request models layered on top of typed_transport."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import Field

from typed_transport.types import (
    HttpRequest as TransportHttpRequest,
    JsonArray,
    JsonObject,
    JsonValue,
    TransportFrozenModel,
    TransportModel,
    coerce_request_model,
    expect_list,
    expect_mapping,
)


class HttpRequest(TransportHttpRequest):
    """Project compatibility request model.

    `typed_transport` keeps its HTTP request schema generic. The main `arb`
    project still needs two exchange-facing compatibility fields while older
    adapters migrate:

    - `market_type`: route hint for spot/perpetual specific callers
    - `signed`: whether the request payload has already been signed
    """

    market_type: str | None = None
    signed: bool = False


def coerce_http_request(payload: HttpRequest | Mapping[str, JsonValue]) -> HttpRequest:
    """Accept either a compatibility request model or a legacy request mapping."""

    return coerce_request_model(HttpRequest, payload)

__all__ = [
    "HttpRequest",
    "JsonArray",
    "JsonObject",
    "JsonValue",
    "TransportFrozenModel",
    "TransportModel",
    "coerce_http_request",
    "expect_list",
    "expect_mapping",
]
