"""Spot long / perpetual short funding strategy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import StrEnum

from arb.funding import DEFAULT_FUNDING_INTERVAL_HOURS
from arb.scanner.cost_model import normalize_rate
from arb.strategy.engine import StrategyAction, StrategyDecision, StrategyState


def _utc_now() -> datetime:
    """返回当前 UTC 时间，供策略评估统一使用。"""

    return datetime.now(tz=timezone.utc)


class SpotPerpReason(StrEnum):
    FUNDING_BELOW_THRESHOLD = "funding_below_threshold"
    BASIS_OUT_OF_RANGE = "basis_out_of_range"
    QUOTE_ACCEPTED = "quote_accepted"
    FUNDING_REVERSED = "funding_reversed"
    HOLDING_PERIOD_EXCEEDED = "holding_period_exceeded"
    HEDGE_RATIO_DRIFT = "hedge_ratio_drift"
    POSITION_HEALTHY = "position_healthy"


@dataclass(slots=True, frozen=True)
class SpotPerpInputs:
    """同所现货多头 / 永续空头策略的输入快照。"""

    # 当前评估的交易标的。
    symbol: str
    # 当前资金费率。
    funding_rate: Decimal
    # 现货侧参考价格，通常使用买入视角价格。
    spot_price: Decimal
    # 永续侧参考价格，通常使用卖出视角价格。
    perp_price: Decimal
    # 资金费率对应的结算周期，单位小时。
    funding_interval_hours: int = DEFAULT_FUNDING_INTERVAL_HOURS
    # 现货腿当前持仓数量。
    spot_quantity: Decimal = Decimal("0")
    # 永续腿当前持仓数量。
    perp_quantity: Decimal = Decimal("0")


@dataclass(slots=True, frozen=True)
class EntryQuoteCheck:
    """入场报价检查结果。"""

    # 当前报价是否满足入场条件。
    accepted: bool
    # 判定原因，例如费率过低、基差过大或报价通过。
    reason: SpotPerpReason
    # 当前现货/永续基差，单位 bps。
    basis_bps: Decimal
    # 已统一折算后的资金费率，便于和阈值直接比较。
    normalized_funding_rate: Decimal = Decimal("0")


class SpotPerpStrategy:
    """同一交易所现货做多 / 永续做空资金费率策略。

    策略目标是：
    - 在资金费率足够高、基差可接受时开仓
    - 持仓期间监控资金费率、持仓时长和双腿数量偏移
    - 在收益条件消失或对冲比例漂移时平仓或再平衡
    """

    def __init__(
        self,
        *,
        min_open_funding_rate: Decimal = Decimal("0.0005"),
        close_funding_rate: Decimal = Decimal("0"),
        threshold_interval_hours: int = DEFAULT_FUNDING_INTERVAL_HOURS,
        max_basis_bps: Decimal = Decimal("25"),
        rebalance_threshold: Decimal = Decimal("0.05"),
        max_holding_period: timedelta = timedelta(days=5),
    ) -> None:
        # 开仓所需的最低资金费率阈值。
        self.min_open_funding_rate = min_open_funding_rate
        # 持仓中若资金费率低于该值，则触发平仓。
        self.close_funding_rate = close_funding_rate
        # 所有资金费率比较都会折算到这个统一周期。
        self.threshold_interval_hours = threshold_interval_hours
        # 允许的最大基差，超过则拒绝开仓。
        self.max_basis_bps = max_basis_bps
        # 目标对冲比例偏离这个阈值时，触发再平衡。
        self.rebalance_threshold = rebalance_threshold
        # 单笔仓位允许持有的最长时间。
        self.max_holding_period = max_holding_period

    def basis_bps(self, spot_price: Decimal, perp_price: Decimal) -> Decimal:
        """计算现货与永续之间的相对价差，单位 bps。"""

        # 现货价格为 0 时无法计算基差，直接返回 0 避免除零。
        if spot_price == 0:
            return Decimal("0")
        return ((perp_price - spot_price) / spot_price) * Decimal("10000")

    def target_hedge_ratio(
        self,
        *,
        spot_quantity: Decimal,
        perp_quantity: Decimal,
    ) -> Decimal:
        """根据双腿当前数量计算实际对冲比例。"""

        # 没有现货腿时无法定义有效对冲比例，直接返回 0。
        if spot_quantity == 0:
            return Decimal("0")
        return perp_quantity / spot_quantity

    def check_entry_quote(self, inputs: SpotPerpInputs) -> EntryQuoteCheck:
        """检查当前报价是否允许开仓。

        检查顺序：
        1. 先计算当前基差
        2. 再把资金费率折算到统一周期
        3. 资金费率不足则拒绝
        4. 基差超限也拒绝
        5. 两项都通过时才允许开仓
        """

        # 先计算当前入场视角下的价差水平。
        basis = self.basis_bps(inputs.spot_price, inputs.perp_price)
        # 不同交易所/品种周期不同，先归一化再和阈值比较。
        normalized_funding_rate = self.normalize_funding_rate(
            inputs.funding_rate,
            interval_hours=inputs.funding_interval_hours,
        )
        # 资金费率太低时，即使结构上能对冲，也不值得开仓。
        if normalized_funding_rate < self.min_open_funding_rate:
            return EntryQuoteCheck(False, SpotPerpReason.FUNDING_BELOW_THRESHOLD, basis, normalized_funding_rate)
        # 基差过大通常意味着冲击成本或收敛风险偏高，因此也拒绝入场。
        if abs(basis) > self.max_basis_bps:
            return EntryQuoteCheck(False, SpotPerpReason.BASIS_OUT_OF_RANGE, basis, normalized_funding_rate)
        return EntryQuoteCheck(True, SpotPerpReason.QUOTE_ACCEPTED, basis, normalized_funding_rate)

    def normalize_funding_rate(
        self,
        funding_rate: Decimal,
        *,
        interval_hours: int,
    ) -> Decimal:
        """把原始资金费率折算到策略统一比较周期。"""

        return normalize_rate(
            funding_rate,
            from_interval_hours=interval_hours,
            to_interval_hours=self.threshold_interval_hours,
        )

    def evaluate(
        self,
        inputs: SpotPerpInputs,
        *,
        state: StrategyState | None = None,
        now: datetime | None = None,
    ) -> StrategyDecision:
        """根据当前输入和策略状态给出动作决策。

        决策分两段：
        - 未持仓：只判断是否满足开仓条件，否则继续观望
        - 已持仓：依次检查资金费率是否反转、持仓时间是否超限、对冲比例是否漂移
        """

        # 没有显式状态时，默认按“未持仓”处理。
        current_state = state or StrategyState()
        # 统一当前评估时间，避免不同调用方各自取时钟。
        current_time = now or _utc_now()
        # 入场相关的基础检查对开仓和持仓态都可复用。
        quote_check = self.check_entry_quote(inputs)
        basis = quote_check.basis_bps
        # 持仓态下用当前双腿数量估算实际对冲比例。
        hedge_ratio = self.target_hedge_ratio(
            spot_quantity=inputs.spot_quantity or Decimal("1"),
            perp_quantity=inputs.perp_quantity or inputs.spot_quantity or Decimal("1"),
        )

        if not current_state.is_open:
            # 未持仓时，只要报价检查通过，就建议开仓。
            if quote_check.accepted:
                return StrategyDecision(
                    StrategyAction.OPEN,
                    reason=quote_check.reason,
                    target_hedge_ratio=Decimal("1"),
                    metadata={
                        "symbol": inputs.symbol,
                        "normalized_funding_rate": quote_check.normalized_funding_rate,
                        "threshold_interval_hours": self.threshold_interval_hours,
                    },
                )
            # 报价不达标时保持观望，并把原因带给上层。
            return StrategyDecision(
                StrategyAction.HOLD,
                reason=quote_check.reason,
                metadata={
                    "symbol": inputs.symbol,
                    "normalized_funding_rate": quote_check.normalized_funding_rate,
                    "threshold_interval_hours": self.threshold_interval_hours,
                },
            )

        # 持仓态下重新计算归一化后的资金费率，用于退出判断。
        normalized_funding_rate = self.normalize_funding_rate(
            inputs.funding_rate,
            interval_hours=inputs.funding_interval_hours,
        )
        # 资金费率跌破关闭阈值时，说明继续持仓的收益基础已经消失。
        if normalized_funding_rate <= self.close_funding_rate:
            return StrategyDecision(StrategyAction.CLOSE, reason=SpotPerpReason.FUNDING_REVERSED, metadata={"symbol": inputs.symbol})

        # 超过最大持仓时间时，主动退出，避免长期暴露。
        if current_state.opened_at and current_time - current_state.opened_at > self.max_holding_period:
            return StrategyDecision(StrategyAction.CLOSE, reason=SpotPerpReason.HOLDING_PERIOD_EXCEEDED, metadata={"symbol": inputs.symbol})

        # 对冲比例偏离过大时，建议再平衡而不是直接平仓。
        if abs(Decimal("1") - hedge_ratio) > self.rebalance_threshold:
            return StrategyDecision(
                StrategyAction.REBALANCE,
                reason=SpotPerpReason.HEDGE_RATIO_DRIFT,
                target_hedge_ratio=Decimal("1"),
                metadata={"symbol": inputs.symbol},
            )

        # 以上条件都未触发时，说明当前仓位仍处于健康状态。
        return StrategyDecision(
            StrategyAction.HOLD,
            reason=SpotPerpReason.POSITION_HEALTHY,
            target_hedge_ratio=hedge_ratio,
            metadata={"symbol": inputs.symbol},
        )
