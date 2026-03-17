"""Control API dependencies."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ApiContext:
    positions_provider: Callable[[], list[dict[str, Any]]] = field(default_factory=lambda: lambda: [])
    strategies_provider: Callable[[], list[dict[str, Any]]] = field(default_factory=lambda: lambda: [])
    orders_provider: Callable[[], list[dict[str, Any]]] = field(default_factory=lambda: lambda: [])
    workflows_provider: Callable[[], list[dict[str, Any]]] = field(default_factory=lambda: lambda: [])
    command_handler: Callable[[dict[str, Any]], dict[str, Any]] = field(
        default_factory=lambda: (lambda command: {"accepted": True, "command_id": "cmd-1", **command})
    )
    command_confirmer: Callable[[str, str], dict[str, Any]] = field(
        default_factory=lambda: (lambda command_id, actor: {"accepted": True, "command_id": command_id, "status": "queued", "requested_by": actor})
    )
    command_canceller: Callable[[str, str], dict[str, Any]] = field(
        default_factory=lambda: (lambda command_id, actor: {"accepted": True, "command_id": command_id, "status": "canceled", "requested_by": actor})
    )
    auth_token: str = "secret-token"

    def require_token(self, token: str | None) -> None:
        if token != self.auth_token:
            raise PermissionError("invalid api token")
