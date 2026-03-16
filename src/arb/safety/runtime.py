"""Runtime safety switches."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


def _read_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class RuntimeSafety:
    read_only: bool = True
    reduce_only: bool = False
    order_submission_enabled: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "RuntimeSafety":
        source = os.environ if env is None else env
        return cls(
            read_only=_read_bool(source.get("ARB_READ_ONLY"), True),
            reduce_only=_read_bool(source.get("ARB_REDUCE_ONLY"), False),
            order_submission_enabled=_read_bool(source.get("ARB_ENABLE_ORDERS"), False),
        )

    def can_submit_orders(self) -> bool:
        return self.order_submission_enabled and not self.read_only

    def can_open_positions(self) -> bool:
        return self.can_submit_orders() and not self.reduce_only
