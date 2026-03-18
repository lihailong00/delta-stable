"""Strategy settings."""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field

from arb.schemas.base import ArbFrozenModel


class StrategyConfig(ArbFrozenModel):
    name: str
    enabled: bool = True
    min_funding_rate: Decimal = Decimal("0")
    symbols: tuple[str, ...] = ()


class StrategySettings(ArbFrozenModel):
    whitelist: set[str] = Field(default_factory=set)
    blacklist: set[str] = Field(default_factory=set)
    strategies: dict[str, StrategyConfig] = Field(default_factory=dict)

    def validate_config(self) -> None:
        overlap = self.whitelist & self.blacklist
        if overlap:
            raise ValueError(f"symbols cannot be in both whitelist and blacklist: {sorted(overlap)}")
        for name, config in self.strategies.items():
            if config.min_funding_rate < 0:
                raise ValueError(f"strategy {name} has negative min_funding_rate")
