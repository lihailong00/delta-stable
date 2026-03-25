"""Command models."""

from __future__ import annotations

from pydantic import Field

from arb.control.enums import ControlSource
from arb.schemas.base import ArbFrozenModel, SerializableValue


class ControlCommand(ArbFrozenModel):
    command_id: str
    action: str
    target: str
    requested_by: str
    source: ControlSource = ControlSource.API
    require_confirmation: bool = False
    payload: dict[str, SerializableValue] = Field(default_factory=dict)
