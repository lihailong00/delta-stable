"""Strategy settings."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(slots=True, frozen=True)
class StrategyConfig:
    name: str
    enabled: bool = True
    min_funding_rate: Decimal = Decimal("0")
    symbols: tuple[str, ...] = ()


@dataclass(slots=True)
class StrategySettings:
    whitelist: set[str] = field(default_factory=set)
    blacklist: set[str] = field(default_factory=set)
    strategies: dict[str, StrategyConfig] = field(default_factory=dict)

    def validate(self) -> None:
        overlap = self.whitelist & self.blacklist
        if overlap:
            raise ValueError(f"symbols cannot be in both whitelist and blacklist: {sorted(overlap)}")
        for name, config in self.strategies.items():
            if config.min_funding_rate < 0:
                raise ValueError(f"strategy {name} has negative min_funding_rate")
