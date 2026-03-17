"""Command models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class ControlCommand:
    command_id: str
    action: str
    target: str
    requested_by: str
    source: str = "api"
    require_confirmation: bool = False
    payload: dict[str, Any] = field(default_factory=dict)
