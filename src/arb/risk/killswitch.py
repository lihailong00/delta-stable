"""Kill switch state."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class KillSwitch:
    active: bool = False
    reduce_only: bool = False
    reason: str | None = None

    def trigger_stop(self, reason: str) -> None:
        self.active = True
        self.reduce_only = True
        self.reason = reason

    def enable_reduce_only(self, reason: str) -> None:
        self.reduce_only = True
        self.reason = reason

    def requires_reduce_only(self) -> bool:
        return self.active or self.reduce_only

    def close_reason(self, default: str = "manual_close") -> str:
        if self.active:
            return "killswitch_active"
        return self.reason or default

    def clear(self) -> None:
        self.active = False
        self.reduce_only = False
        self.reason = None
