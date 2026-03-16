"""Configuration loading helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


def _read_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True, frozen=True)
class AppConfig:
    """Runtime configuration shared across modules."""

    env: str = "dev"
    log_level: str = "INFO"
    timezone: str = "UTC"
    data_dir: Path = Path("var/data")
    dry_run: bool = True

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "AppConfig":
        source = os.environ if env is None else env
        data_dir = Path(source.get("ARB_DATA_DIR", "var/data"))
        return cls(
            env=source.get("ARB_ENV", "dev"),
            log_level=source.get("ARB_LOG_LEVEL", "INFO").upper(),
            timezone=source.get("ARB_TIMEZONE", "UTC"),
            data_dir=data_dir,
            dry_run=_read_bool(source.get("ARB_DRY_RUN"), True),
        )


def load_config(env: Mapping[str, str] | None = None) -> AppConfig:
    """Load application configuration from environment variables."""

    return AppConfig.from_env(env)


__all__ = ["AppConfig", "load_config"]
