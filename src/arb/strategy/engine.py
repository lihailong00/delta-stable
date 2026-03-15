"""Strategy state machine helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from decimal import Decimal


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


class StrategyAction(StrEnum):
    OPEN = "open"
    HOLD = "hold"
    CLOSE = "close"
    REBALANCE = "rebalance"


@dataclass(slots=True, frozen=True)
class StrategyDecision:
    action: StrategyAction
    reason: str
    target_hedge_ratio: Decimal = Decimal("1")
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class StrategyState:
    is_open: bool = False
    opened_at: datetime | None = None
    hedge_ratio: Decimal = Decimal("1")

    def open(self, hedge_ratio: Decimal, opened_at: datetime | None = None) -> None:
        self.is_open = True
        self.hedge_ratio = hedge_ratio
        self.opened_at = opened_at or utc_now()

    def close(self) -> None:
        self.is_open = False
        self.opened_at = None
        self.hedge_ratio = Decimal("0")


class StrategyEngine:
    """Apply generic open/hold/close/rebalance state transitions."""

    def transition(self, state: StrategyState, decision: StrategyDecision) -> StrategyState:
        if decision.action is StrategyAction.OPEN:
            state.open(decision.target_hedge_ratio)
        elif decision.action is StrategyAction.CLOSE:
            state.close()
        elif decision.action is StrategyAction.REBALANCE:
            state.hedge_ratio = decision.target_hedge_ratio
        return state
