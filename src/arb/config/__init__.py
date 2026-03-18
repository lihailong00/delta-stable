"""Configuration loading helpers."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from pydantic import Field, field_validator

from arb.schemas.base import ArbFrozenModel


def _read_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class AppConfig(ArbFrozenModel):
    """Runtime configuration shared across modules."""

    env: str = "dev"
    log_level: str = "INFO"
    timezone: str = "UTC"
    data_dir: Path = Field(default_factory=lambda: Path("var/data"))
    dry_run: bool = True

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: str) -> str:
        return str(value).upper()

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "AppConfig":
        source = os.environ if env is None else env
        return cls.model_validate(
            {
                "env": source.get("ARB_ENV", "dev"),
                "log_level": source.get("ARB_LOG_LEVEL", "INFO"),
                "timezone": source.get("ARB_TIMEZONE", "UTC"),
                "data_dir": Path(source.get("ARB_DATA_DIR", "var/data")),
                "dry_run": _read_bool(source.get("ARB_DRY_RUN"), True),
            }
        )


def load_config(env: Mapping[str, str] | None = None) -> AppConfig:
    """Load application configuration from environment variables."""

    return AppConfig.from_env(env)


__all__ = ["AppConfig", "load_config"]
