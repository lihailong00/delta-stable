"""Feishu integration schemas."""

from __future__ import annotations

from pydantic import Field

from arb.schemas.base import ArbFrozenModel, SerializableValue


class FeishuCard(ArbFrozenModel):
    config: dict[str, SerializableValue]
    header: dict[str, SerializableValue]
    elements: list[dict[str, SerializableValue]]


class FeishuTransportRequest(ArbFrozenModel):
    method: str
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    params: dict[str, str] = Field(default_factory=dict)
    json_body: dict[str, SerializableValue] = Field(default_factory=dict, alias="json")


class FeishuParsedCallback(ArbFrozenModel):
    type: str
    action: dict[str, SerializableValue] = Field(default_factory=dict)
    operator_id: str | None = None
    event: dict[str, SerializableValue] = Field(default_factory=dict)
    challenge: str | None = None
