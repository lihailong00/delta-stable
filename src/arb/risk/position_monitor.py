"""Ongoing position risk monitoring for funding arbitrage service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from collections.abc import Mapping, Sequence
from typing import Protocol

from pydantic import Field

from arb.funding import DEFAULT_FUNDING_INTERVAL_HOURS
from arb.market.schemas import MarketSnapshot, coerce_funding_rate, coerce_ticker
from arb.market.spot_perp_view import SpotPerpQuoteView, build_spot_perp_view
from arb.models import FundingRate, MarketType, Ticker
from arb.risk.checks import RiskAlert, RiskChecker, RiskReason
from arb.scanner.cost_model import normalize_rate
from arb.schemas.base import ArbFrozenModel, ArbModel


class PositionMonitorSnapshot(ArbFrozenModel):
    """持仓监控使用的归一化快照。

    `PositionMonitor` 不直接依赖某一种原始行情结构，而是先把外部输入收敛成
    ticker / funding / spot-perp view 这三个监控需要的最小信息集合。
    """

    # 单腿行情主报价对象，至少需要能提供 last 或 bid 等价格字段。
    ticker: Ticker
    # 可选的资金费率信息。
    funding: FundingRate | None = None
    # 可选的现货/永续配对视图，用于基差检查。
    view: SpotPerpQuoteView | None = None

    @classmethod
    def from_snapshot(
        cls,
        snapshot: MarketSnapshot | Mapping[str, object],
        *,
        symbol: str,
    ) -> "PositionMonitorSnapshot":
        """把外部快照归一化成监控模块可直接消费的结构。

        支持两类输入：
        - `MarketSnapshot`：直接抽取 ticker / funding
        - 原始映射对象：尝试从 `ticker`、`funding`、`view` 三个字段重建所需信息
        """

        # 已经是标准快照时，直接提取监控所需字段即可。
        if isinstance(snapshot, MarketSnapshot):
            view = None
            view_payload = snapshot.view
            if isinstance(view_payload, Mapping) and snapshot.funding is not None:
                spot_ticker = view_payload.get("spot_ticker")
                perp_ticker = view_payload.get("perp_ticker")
                if isinstance(spot_ticker, Mapping) and isinstance(perp_ticker, Mapping):
                    view = build_spot_perp_view(
                        exchange=snapshot.funding.exchange,
                        symbol=symbol,
                        spot_ticker=dict(spot_ticker),
                        perp_ticker=dict(perp_ticker),
                        funding=snapshot.funding,
                    )
            return cls(ticker=snapshot.ticker, funding=snapshot.funding, view=view)
        ticker_payload = snapshot.get("ticker")
        # ticker 是监控的最低必需信息，没有它就无法继续。
        if not isinstance(ticker_payload, Mapping):
            raise TypeError("snapshot.ticker is required")
        funding_payload = snapshot.get("funding")
        view_payload = snapshot.get("view")
        view = None
        # 如果上游额外提供了现货/永续双腿视图，则一并重建，供后续基差检查复用。
        if isinstance(view_payload, Mapping) and isinstance(funding_payload, Mapping):
            spot_ticker = view_payload.get("spot_ticker")
            perp_ticker = view_payload.get("perp_ticker")
            if isinstance(spot_ticker, Mapping) and isinstance(perp_ticker, Mapping):
                # exchange 优先取 funding 中的值，避免 ticker 与 funding 来源不一致。
                exchange = str(funding_payload.get("exchange", ticker_payload.get("exchange", "")))
                view = build_spot_perp_view(
                    exchange=exchange,
                    symbol=symbol,
                    spot_ticker=dict(spot_ticker),
                    perp_ticker=dict(perp_ticker),
                    funding=dict(funding_payload),
                )
        return cls(
            # ticker 会被统一转换成标准模型，并补齐 symbol / market_type 等默认值。
            ticker=coerce_ticker(
                dict(ticker_payload),
                default_symbol=symbol,
                default_market_type=MarketType.PERPETUAL,
            ),
            funding=(
                # funding 存在时也统一归一化，方便后续直接读取 rate 等字段。
                coerce_funding_rate(dict(funding_payload), default_symbol=symbol)
                if isinstance(funding_payload, Mapping)
                else None
            ),
            view=view,
        )


class PositionMonitorDecision(ArbModel):
    """持仓监控的输出结果。"""

    # 本次评估命中的所有风险告警。
    alerts: list[RiskAlert] = Field(default_factory=list)
    # 若有“触发平仓”的告警，则给出本轮最应该采用的平仓原因；否则为 None。
    close_reason: str | None = None

    @property
    def should_close(self) -> bool:
        """是否应该关闭当前持仓。"""

        return self.close_reason is not None


@dataclass(slots=True, frozen=True)
class PositionRiskContext:
    """单次持仓风险评估的统一上下文。

    原来 `evaluate()` 里散落的输入参数和中间归一化结果，现在统一收进这个对象。
    这样每条风险规则只需要读取 `context`，不需要再关心外层调用协议。
    """

    # 当前评估的交易标的。
    symbol: str
    # 已归一化的持仓监控快照。
    snapshot: PositionMonitorSnapshot
    # 现货腿数量。
    spot_quantity: Decimal
    # 永续腿数量。
    perp_quantity: Decimal
    # 开仓时间。
    opened_at: datetime | None
    # 最大持仓时长。
    max_holding_period: timedelta
    # 最低预期资金费率收益。
    min_expected_rate: Decimal
    # 原始资金费率对应的周期，单位小时。
    funding_interval_hours: int = DEFAULT_FUNDING_INTERVAL_HOURS
    # 风控比较时统一折算到的周期，单位小时。
    comparison_interval_hours: int = DEFAULT_FUNDING_INTERVAL_HOURS
    # 强平价格；若为空则跳过相关检查。
    liquidation_price: Decimal | None = None
    # 当前评估时间；为空时由底层规则自行决定默认时间。
    now: datetime | None = None

    @property
    def funding(self) -> FundingRate | None:
        """返回归一化后的资金费率对象。"""

        return self.snapshot.funding

    @property
    def view(self) -> SpotPerpQuoteView | None:
        """返回归一化后的现货/永续配对视图。"""

        return self.snapshot.view

    @property
    def mark_price(self) -> Decimal:
        """返回当前持仓的标记价格。"""

        return self.snapshot.ticker.last

    @property
    def normalized_funding_rate(self) -> Decimal:
        """把资金费率折算到统一比较周期后的结果。"""

        funding_rate = self.funding.rate if self.funding is not None else Decimal("0")
        return normalize_rate(
            funding_rate,
            from_interval_hours=self.funding_interval_hours,
            to_interval_hours=self.comparison_interval_hours,
        )


class PositionRiskRule(Protocol):
    """持仓风险规则接口。

    任何规则只要实现 `evaluate(context)`，就可以被 `PositionMonitor` 注册并执行。
    """

    def evaluate(self, context: PositionRiskContext) -> RiskAlert | None:
        """基于统一上下文评估一条风险规则。"""


@dataclass(slots=True, frozen=True)
class FundingReversalRule(PositionRiskRule):
    """资金费率反转检查规则。"""

    risk_checker: RiskChecker

    def evaluate(self, context: PositionRiskContext) -> RiskAlert | None:
        return self.risk_checker.check_funding_reversal(
            symbol=context.symbol,
            current_rate=context.normalized_funding_rate,
            min_expected_rate=context.min_expected_rate,
        )


@dataclass(slots=True, frozen=True)
class HoldingPeriodRule(PositionRiskRule):
    """持仓超时检查规则。"""

    risk_checker: RiskChecker

    def evaluate(self, context: PositionRiskContext) -> RiskAlert | None:
        return self.risk_checker.check_holding_period(
            symbol=context.symbol,
            opened_at=context.opened_at,
            max_holding_period=context.max_holding_period,
            now=context.now,
        )


@dataclass(slots=True, frozen=True)
class NakedLegRule(PositionRiskRule):
    """双腿数量失衡检查规则。"""

    risk_checker: RiskChecker
    tolerance: Decimal

    def evaluate(self, context: PositionRiskContext) -> RiskAlert | None:
        return self.risk_checker.check_naked_leg(
            symbol=context.symbol,
            long_quantity=context.spot_quantity,
            short_quantity=context.perp_quantity,
            tolerance=self.tolerance,
        )


@dataclass(slots=True, frozen=True)
class BasisRule(PositionRiskRule):
    """现货/永续基差检查规则。"""

    risk_checker: RiskChecker
    max_basis_bps: Decimal

    def evaluate(self, context: PositionRiskContext) -> RiskAlert | None:
        view = context.view
        if view is None:
            return None
        return self.risk_checker.check_basis(
            symbol=context.symbol,
            spot_price=view.spot_ticker.ask,
            perp_price=view.perp_ticker.bid,
            max_basis_bps=self.max_basis_bps,
        )


@dataclass(slots=True, frozen=True)
class LiquidationBufferRule(PositionRiskRule):
    """强平缓冲检查规则。"""

    risk_checker: RiskChecker
    min_buffer_bps: Decimal

    def evaluate(self, context: PositionRiskContext) -> RiskAlert | None:
        if context.liquidation_price is None:
            return None
        return self.risk_checker.check_liquidation_buffer(
            symbol=context.symbol,
            mark_price=context.mark_price,
            liquidation_price=context.liquidation_price,
            min_buffer_bps=self.min_buffer_bps,
        )


class PositionMonitor:
    """实时评估资金费率套利持仓的风险状态。

    这个类会把多条独立风险规则组合起来，输出：
    - 当前命中的全部告警
    - 是否应该平仓
    - 如果要平仓，优先采用哪个关闭原因
    """

    def __init__(
        self,
        *,
        risk_checker: RiskChecker | None = None,
        max_basis_bps: Decimal = Decimal("25"),
        min_buffer_bps: Decimal = Decimal("30"),
        naked_tolerance: Decimal = Decimal("0.02"),
        rules: Sequence[PositionRiskRule] | None = None,
        close_reasons: frozenset[RiskReason] | None = None,
    ) -> None:
        # 基础风控规则集合，可由外部注入自定义实现。
        self.risk_checker = risk_checker or RiskChecker()
        # 允许的最大现货/永续基差，超出则视为异常。
        self.max_basis_bps = max_basis_bps
        # 标记价格与强平价之间要求保留的最小安全缓冲。
        self.min_buffer_bps = min_buffer_bps
        # 允许的双腿数量相对偏差。
        self.naked_tolerance = naked_tolerance
        # 风险规则采用可注册列表，后续新增规则时不需要再修改 evaluate 主流程。
        self.rules = tuple(rules) if rules is not None else self._default_rules()
        # 命中后会触发平仓的风险原因集合；未在集合中的原因只告警不平仓。
        self.close_reasons = close_reasons or self._default_close_reasons()

    def _default_rules(self) -> tuple[PositionRiskRule, ...]:
        """构建默认启用的内置风险规则列表。"""

        return (
            FundingReversalRule(self.risk_checker),
            HoldingPeriodRule(self.risk_checker),
            NakedLegRule(self.risk_checker, tolerance=self.naked_tolerance),
            BasisRule(self.risk_checker, max_basis_bps=self.max_basis_bps),
            LiquidationBufferRule(self.risk_checker, min_buffer_bps=self.min_buffer_bps),
        )

    def _default_close_reasons(self) -> frozenset[RiskReason]:
        """返回默认会触发平仓的风险原因集合。

        `holding_period_exceeded` 和 `basis_out_of_range` 默认只做告警，
        不直接由 PositionMonitor 触发强制平仓。
        """

        return frozenset(
            {
                RiskReason.FUNDING_REVERSAL,
                RiskReason.NAKED_LEG,
                RiskReason.LIQUIDATION_BUFFER_LOW,
            }
        )

    def evaluate(
        self,
        *,
        symbol: str,
        snapshot: PositionMonitorSnapshot | MarketSnapshot | Mapping[str, object],
        spot_quantity: Decimal,
        perp_quantity: Decimal,
        opened_at: datetime | None,
        max_holding_period: timedelta,
        min_expected_rate: Decimal,
        funding_interval_hours: int = DEFAULT_FUNDING_INTERVAL_HOURS,
        comparison_interval_hours: int = DEFAULT_FUNDING_INTERVAL_HOURS,
        liquidation_price: Decimal | None = None,
        now: datetime | None = None,
    ) -> PositionMonitorDecision:
        """对单个活跃持仓做一次风险评估。

        评估顺序大致为：
        1. 先把输入快照归一化
        2. 检查资金费率是否反转
        3. 检查持仓时间是否超限
        4. 检查双腿数量是否失衡
        5. 如果有 spot-perp view，则继续检查基差
        6. 如果有强平价，则继续检查强平缓冲

        最终会综合所有告警，选出一个最优先的 `close_reason`。
        """

        # 统一输入快照形状，避免后续每个检查都处理不同结构。
        normalized_snapshot = (
            snapshot
            if isinstance(snapshot, PositionMonitorSnapshot)
            else PositionMonitorSnapshot.from_snapshot(snapshot, symbol=symbol)
        )
        # 所有规则共享同一个上下文对象，避免新增规则时继续扩张 evaluate 参数拼装逻辑。
        context = PositionRiskContext(
            symbol=symbol,
            snapshot=normalized_snapshot,
            spot_quantity=spot_quantity,
            perp_quantity=perp_quantity,
            opened_at=opened_at,
            max_holding_period=max_holding_period,
            min_expected_rate=min_expected_rate,
            funding_interval_hours=funding_interval_hours,
            comparison_interval_hours=comparison_interval_hours,
            liquidation_price=liquidation_price,
            now=now,
        )
        alerts: list[RiskAlert] = []
        # 按注册顺序执行风险规则；每条规则只关心自己的判断，不关心整体流程。
        for rule in self.rules:
            alert = rule.evaluate(context)
            if alert is not None:
                alerts.append(alert)

        # 不是所有告警都会导致平仓；这里只从允许触发平仓的原因里挑选 close_reason。
        close_alerts = [alert for alert in alerts if alert.reason in self.close_reasons]
        close_reason = (
            self.risk_checker.choose_close_reason(close_alerts, default="manual_close")
            if close_alerts
            else None
        )
        return PositionMonitorDecision(alerts=alerts, close_reason=close_reason)
