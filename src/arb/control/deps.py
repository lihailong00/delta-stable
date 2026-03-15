"""Control API dependencies."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ApiContext:
    positions_provider: Callable[[], list[dict[str, Any]]] = field(default_factory=lambda: lambda: [])
    strategies_provider: Callable[[], list[dict[str, Any]]] = field(default_factory=lambda: lambda: [])
    command_handler: Callable[[dict[str, Any]], dict[str, Any]] = field(
        default_factory=lambda: (lambda command: {"accepted": True, "command_id": "cmd-1", **command})
    )
    auth_token: str = "secret-token"

    def require_token(self, token: str | None) -> None:
        if token != self.auth_token:
            raise PermissionError("invalid api token")
