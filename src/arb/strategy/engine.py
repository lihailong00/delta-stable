"""Strategy state machine helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from decimal import Decimal


def utc_now() -> datetime:
    """返回当前 UTC 时间，供策略状态记录统一使用。"""

    return datetime.now(tz=timezone.utc)


class StrategyAction(StrEnum):
    """策略层允许输出的标准动作枚举。

    各具体策略只需要产出这些动作之一，执行层和状态机再根据动作做统一处理。
    这样可以把“策略判断”和“状态变更”分开，避免每个策略都自己维护状态流转。
    """

    OPEN = "open"
    HOLD = "hold"
    CLOSE = "close"
    REBALANCE = "rebalance"


@dataclass(slots=True, frozen=True)
class StrategyDecision:
    """策略一次评估后的输出结果。

    字段说明：
    - `action`: 本次评估建议执行的动作，例如开仓、持有、平仓、再平衡
    - `reason`: 触发这个动作的原因，方便日志、调试和回测解释
    - `target_hedge_ratio`: 目标对冲比例；对 OPEN / REBALANCE 特别重要
    - `metadata`: 可选补充信息，用于挂载额外上下文，不影响状态机主逻辑
    """

    action: StrategyAction
    reason: str
    target_hedge_ratio: Decimal = Decimal("1")
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class StrategyState:
    """策略状态机持有的最小运行时状态。

    这里不关心具体仓位明细和订单，只关心策略是否处于“已开仓”状态、
    什么时候开的仓，以及当前认为的目标对冲比例是多少。
    """

    # 当前策略是否处于持仓中。
    is_open: bool = False
    # 最近一次开仓时间；未开仓时为 None。
    opened_at: datetime | None = None
    # 当前状态下认为应维持的对冲比例。
    hedge_ratio: Decimal = Decimal("1")

    def open(self, hedge_ratio: Decimal, opened_at: datetime | None = None) -> None:
        """把状态切换为已开仓，并记录开仓时间与目标对冲比例。

        如果调用方没有显式传入 `opened_at`，这里会自动使用当前 UTC 时间，
        保证策略状态里始终有一致的时间基准。
        """

        self.is_open = True
        self.hedge_ratio = hedge_ratio
        self.opened_at = opened_at or utc_now()

    def close(self) -> None:
        """把状态切换为未开仓，并清空开仓时间。

        平仓后把 `hedge_ratio` 归零，表示当前没有需要维持的对冲头寸。
        """

        self.is_open = False
        self.opened_at = None
        self.hedge_ratio = Decimal("0")


class StrategyEngine:
    """负责把策略决策应用到策略状态上的通用状态机。

    具体策略只需要负责“判断应该做什么”，
    这个引擎负责“把判断真正落到状态对象上”。
    """

    def transition(self, state: StrategyState, decision: StrategyDecision) -> StrategyState:
        """根据策略决策更新状态，并返回更新后的同一个状态对象。

        处理规则：
        - OPEN: 进入持仓状态，并写入目标对冲比例
        - CLOSE: 清空持仓状态
        - REBALANCE: 持仓仍然存在，但更新目标对冲比例
        - HOLD: 不做任何状态修改，直接返回原状态
        """

        # 开仓决策：把状态切到 is_open=True，并记录新的对冲比例与开仓时间。
        if decision.action is StrategyAction.OPEN:
            state.open(decision.target_hedge_ratio)
        # 平仓决策：把策略状态重置为未持仓。
        elif decision.action is StrategyAction.CLOSE:
            state.close()
        # 再平衡决策：不改变是否开仓，只更新目标对冲比例。
        elif decision.action is StrategyAction.REBALANCE:
            state.hedge_ratio = decision.target_hedge_ratio
        # HOLD 不进入任何分支，表示当前状态保持不变。
        return state
