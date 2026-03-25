"""Risk check primitives."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import StrEnum


class RiskSeverity(StrEnum):
    """风控告警严重级别枚举。"""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RiskReason(StrEnum):
    """风控规则产出的标准原因枚举。"""

    KILLSWITCH_ACTIVE = "killswitch_active"
    NAKED_LEG = "naked_leg"
    LIQUIDATION_BUFFER_LOW = "liquidation_buffer_low"
    FUNDING_REVERSAL = "funding_reversal"
    HOLDING_PERIOD_EXCEEDED = "holding_period_exceeded"
    BASIS_OUT_OF_RANGE = "basis_out_of_range"

    @property
    def severity(self) -> RiskSeverity:
        """返回该风险原因对应的默认严重级别。"""

        return RISK_REASON_SEVERITY[self]


RISK_REASON_SEVERITY = {
    RiskReason.KILLSWITCH_ACTIVE: RiskSeverity.HIGH,
    RiskReason.NAKED_LEG: RiskSeverity.HIGH,
    RiskReason.LIQUIDATION_BUFFER_LOW: RiskSeverity.HIGH,
    RiskReason.FUNDING_REVERSAL: RiskSeverity.MEDIUM,
    RiskReason.HOLDING_PERIOD_EXCEEDED: RiskSeverity.MEDIUM,
    RiskReason.BASIS_OUT_OF_RANGE: RiskSeverity.MEDIUM,
}


@dataclass(slots=True, frozen=True)
class RiskAlert:
    """单条风控告警。

    风控检查函数返回的统一结构，供上层工作流决定是否需要平仓、
    以及用什么原因记录这次风险触发。
    """

    # 告警原因标识，供路由、平仓原因选择和日志使用。
    reason: RiskReason
    # 告警对应的交易标的。
    symbol: str

    def __post_init__(self) -> None:
        """兼容调用方传入字符串，并在对象内部统一归一化成枚举。"""

        object.__setattr__(self, "reason", RiskReason(self.reason))

    @property
    def severity(self) -> RiskSeverity:
        """从风险原因派生出的严重级别。"""

        return self.reason.severity


def _utc_now() -> datetime:
    """返回当前 UTC 时间，供持仓时长检查统一使用。"""

    return datetime.now(tz=timezone.utc)


class RiskChecker:
    """评估资金费率套利常见风险条件。

    这个类只负责做“规则判断”，不直接执行任何平仓动作。
    上层工作流会根据这里产出的 `RiskAlert` 决定是否退出仓位。
    """

    # 当同时命中多个风险时，优先级越小越应优先作为平仓原因。
    CLOSE_PRIORITY = {
        RiskReason.KILLSWITCH_ACTIVE: 0,  # 最高优先级：紧急停止
        RiskReason.NAKED_LEG: 1,  # 极高风险：单腿裸露
        RiskReason.LIQUIDATION_BUFFER_LOW: 2,  # 高风险：保证金不足
        RiskReason.FUNDING_REVERSAL: 3,  # 中风险：费率反转
        RiskReason.HOLDING_PERIOD_EXCEEDED: 4,  # 超时：持有太久
        RiskReason.BASIS_OUT_OF_RANGE: 5,  # 低风险：价差异常
    }

    def check_liquidation_buffer(
        self,
        *,
        symbol: str,
        mark_price: Decimal,
        liquidation_price: Decimal,
        min_buffer_bps: Decimal,
    ) -> RiskAlert | None:
        """检查当前价格距离强平价的安全缓冲是否过低。

        计算逻辑：
        - 缓冲 bps = `abs(mark_price - liquidation_price) / mark_price * 10000`
        - 若结果小于最小安全缓冲 `min_buffer_bps`，则触发高优先级风险告警
        """

        # 标记价格为 0 时无法计算有效缓冲，直接忽略该检查。
        if mark_price == 0:
            return None
        buffer_bps = abs(mark_price - liquidation_price) / mark_price * Decimal("10000")
        if buffer_bps < min_buffer_bps:
            return RiskAlert(RiskReason.LIQUIDATION_BUFFER_LOW, symbol)
        return None

    def check_basis(
        self,
        *,
        symbol: str,
        spot_price: Decimal,
        perp_price: Decimal,
        max_basis_bps: Decimal,
    ) -> RiskAlert | None:
        """检查现货与永续价格之间的基差是否超出可接受范围。"""

        # 现货价格为 0 时无法计算基差，直接跳过。
        if spot_price == 0:
            return None
        # 基差采用相对现货价格的 bps 表达，便于统一设阈值。
        basis_bps = abs(perp_price - spot_price) / spot_price * Decimal("10000")
        if basis_bps > max_basis_bps:
            return RiskAlert(RiskReason.BASIS_OUT_OF_RANGE, symbol)
        return None

    def check_funding_reversal(
        self,
        *,
        symbol: str,
        current_rate: Decimal,
        min_expected_rate: Decimal,
    ) -> RiskAlert | None:
        """检查资金费率是否已经低于策略要求的最低收益阈值。"""

        if current_rate < min_expected_rate:
            return RiskAlert(RiskReason.FUNDING_REVERSAL, symbol)
        return None

    def check_holding_period(
        self,
        *,
        symbol: str,
        opened_at: datetime | None,
        max_holding_period: timedelta,
        now: datetime | None = None,
    ) -> RiskAlert | None:
        """检查持仓时间是否已经超过允许上限。"""

        # 没有开仓时间时无法判断持仓时长，直接视为无告警。
        if opened_at is None:
            return None
        current_time = now or _utc_now()
        if current_time - opened_at > max_holding_period:
            return RiskAlert(RiskReason.HOLDING_PERIOD_EXCEEDED, symbol)
        return None

    def check_naked_leg(
        self,
        *,
        symbol: str,
        long_quantity: Decimal,
        short_quantity: Decimal,
        tolerance: Decimal = Decimal("0.02"),
    ) -> RiskAlert | None:
        """检查对冲双腿是否已经明显失衡，形成裸露方向风险。

        `tolerance` 表示允许的相对偏差比例，默认 2%。
        """

        # 双腿都为 0 说明没有实际头寸，不构成裸腿风险。
        if long_quantity == 0 and short_quantity == 0:
            return None
        # 用较大的一侧作为基准，避免小仓位下偏差被放大。
        baseline = max(long_quantity, short_quantity, Decimal("1"))
        imbalance = abs(long_quantity - short_quantity) / baseline
        if imbalance > tolerance:
            return RiskAlert(RiskReason.NAKED_LEG, symbol)
        return None

    def choose_close_reason(
        self,
        alerts: list[RiskAlert],
        *,
        default: str = "manual_close",
    ) -> str:
        """从多条风险告警中选出最适合作为平仓原因的一条。

        如果没有任何告警，则返回调用方提供的默认原因。
        """

        if not alerts:
            return default
        # 按预设优先级排序，优先返回更紧急、更基础的风险原因。
        ranked = sorted(
            alerts,
            key=lambda alert: self.CLOSE_PRIORITY.get(alert.reason, len(self.CLOSE_PRIORITY)),
        )
        return ranked[0].reason
