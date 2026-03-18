"""Live runtime configuration."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Literal

from arb.config import AppConfig, _read_bool


class LiveRuntimeConfig(AppConfig):
    mode: Literal["live", "testnet"] = "testnet"
    read_only: bool = True
    orders_enabled: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "LiveRuntimeConfig":
        source = os.environ if env is None else env
        base = AppConfig.from_env(source)
        return cls.model_validate(
            {
                **base.to_dict(),
                "mode": source.get("ARB_RUNTIME_MODE", "testnet").lower(),
                "read_only": _read_bool(source.get("ARB_READ_ONLY"), True),
                "orders_enabled": _read_bool(source.get("ARB_ENABLE_ORDERS"), False),
            }
        )

    @property
    def use_testnet(self) -> bool:
        return self.mode == "testnet"


def load_live_config(env: Mapping[str, str] | None = None) -> LiveRuntimeConfig:
    return LiveRuntimeConfig.from_env(env)
