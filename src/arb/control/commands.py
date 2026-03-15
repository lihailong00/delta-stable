"""Command models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class ControlCommand:
    command_id: str
    action: str
    target: str
    requested_by: str
    source: str = "api"
    require_confirmation: bool = False
