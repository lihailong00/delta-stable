"""Exchange settings."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True, frozen=True)
class ExchangeAccountConfig:
    name: str
    enabled: bool = True
    api_key_env: str | None = None
    api_secret_env: str | None = None


@dataclass(slots=True)
class ExchangeSettings:
    exchanges: dict[str, ExchangeAccountConfig] = field(default_factory=dict)

    def validate(self) -> None:
        for name, config in self.exchanges.items():
            if config.enabled and (not config.api_key_env or not config.api_secret_env):
                raise ValueError(f"exchange {name} is enabled but missing credential env vars")
