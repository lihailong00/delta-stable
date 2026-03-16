"""Live runtime configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from arb.config import AppConfig, _read_bool


@dataclass(slots=True, frozen=True)
class LiveRuntimeConfig(AppConfig):
    mode: str = "testnet"
    read_only: bool = True
    orders_enabled: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "LiveRuntimeConfig":
        source = os.environ if env is None else env
        base = AppConfig.from_env(source)
        mode = source.get("ARB_RUNTIME_MODE", "testnet").lower()
        if mode not in {"live", "testnet"}:
            raise ValueError(f"unsupported runtime mode: {mode}")
        return cls(
            env=base.env,
            log_level=base.log_level,
            timezone=base.timezone,
            data_dir=base.data_dir,
            dry_run=base.dry_run,
            mode=mode,
            read_only=_read_bool(source.get("ARB_READ_ONLY"), True),
            orders_enabled=_read_bool(source.get("ARB_ENABLE_ORDERS"), False),
        )


def load_live_config(env: Mapping[str, str] | None = None) -> LiveRuntimeConfig:
    return LiveRuntimeConfig.from_env(env)
