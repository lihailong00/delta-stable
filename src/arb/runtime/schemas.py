"""运行时状态、扫描结果与恢复计划相关的强类型模型。

这个文件里的模型主要服务于运行时编排层，目标不是表达交易所原始数据，
而是把“扫描得到什么”“当前持仓是什么”“一次运行做了什么”“系统要如何恢复”
这些更高层的状态收敛成统一结构。

可以按职责把它们分成几组：

1. 活跃仓位模型
   - `ActiveFundingArb`
   - `ActiveCrossExchangeArb`

2. 扫描机会与扫描输出模型
   - `CrossExchangeOpportunity`
   - `RealtimeScanResult`

3. 一次运行的聚合结果模型
   - `FundingArbRunResult`
   - `CrossExchangeRunResult`

4. 持久化与恢复相关模型
   - `WorkflowStateRecord`
   - `RecoveryPlan`
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import ConfigDict, Field

from arb.market.schemas import MarketSnapshot
from arb.portfolio.reconciler import ReconciliationReport
from arb.runtime.enums import WorkflowStatus
from arb.scanner.funding_scanner import FundingOpportunity
from arb.schemas.base import ArbFrozenModel, ArbModel, SerializableValue
from arb.strategy.engine import StrategyState
from arb.workflows.close_position import ClosePositionResult
from arb.workflows.open_position import OpenPositionResult


class ActiveFundingArb(ArbModel):
    """单交易所资金费率套利的当前活跃仓位。

    这个模型描述的是已经开出来、目前仍处于运行中的一组仓位状态。
    对这类策略来说，典型结构是：
    - 现货腿做多
    - 永续合约腿做空

    因此这里同时保存 spot/perp 两条腿的数量，以及该 workflow 当前的策略状态。
    """

    # === 身份标识 ===
    workflow_id: str  # 唯一标识符，如 "funding_spot_perp:binance:BTCUSDT"

    # === 基础信息 ===
    exchange: str  # 交易所，如 "binance"
    symbol: str  # 交易对，如 "BTCUSDT"

    # === 仓位信息 ===
    spot_quantity: Decimal  # 现货腿的实际数量
    perp_quantity: Decimal  # 永续合约腿的实际数量

    # === 时间信息 ===
    opened_at: datetime  # 开仓时间

    # === 风控信息 ===
    liquidation_price: Decimal | None = None  # 强平价格（如果有）

    # === 策略信息 ===
    route: object | None = None  # 执行路径（可选）
    state: StrategyState = Field(default_factory=StrategyState)  # 策略状态（如是否已对冲）

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        arbitrary_types_allowed=True,
    )


class CrossExchangeOpportunity(ArbFrozenModel):
    """跨交易所价差机会。

    这个模型只表达“机会本身”，不表达是否已经执行，也不携带持仓状态。
    典型含义是：
    - 在 `long_exchange` 以较低价格买入
    - 在 `short_exchange` 以较高价格卖出
    - `spread_rate` 表示这两个价格之间的相对价差
    """

    symbol: str
    long_exchange: str
    short_exchange: str
    spread_rate: Decimal
    long_price: Decimal
    short_price: Decimal


class ActiveCrossExchangeArb(ArbModel):
    """跨交易所套利的当前活跃仓位。

    与 `ActiveFundingArb` 类似，这也是“已经开仓后”的运行态对象。
    区别在于这里不是现货/永续两条腿，而是两个交易所上的对冲腿：
    - `long_exchange` 上的多头数量
    - `short_exchange` 上的空头数量
    """

    workflow_id: str
    symbol: str
    long_exchange: str
    short_exchange: str
    quantity: Decimal
    long_quantity: Decimal
    short_quantity: Decimal
    opened_at: datetime
    state: StrategyState = Field(default_factory=StrategyState)

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        arbitrary_types_allowed=True,
    )


class WorkflowStateRecord(ArbFrozenModel):
    """单个 workflow 的可持久化状态记录。

    这个模型用于把运行时中的 workflow 关键状态写入 repository 或恢复介质。
    设计重点是“稳定、可序列化、可恢复”，因此：
    - `status` 表示当前生命周期阶段
    - `payload` 用于补充状态细节
    - `updated_at` 记录最近更新时间
    """

    workflow_id: str
    workflow_type: str
    exchange: str
    symbol: str
    status: WorkflowStatus
    payload: dict[str, SerializableValue] = Field(default_factory=dict)  # 状态附加信息，如告警、执行摘要、风控上下文等
    updated_at: str | None = None  # 最近更新时间，通常使用 ISO 8601 字符串，便于持久化与跨进程传输


class RealtimeScanResult(ArbFrozenModel):
    """一轮实时扫描的完整结果。

    这是 `RealtimeScanner.scan_once()` 的直接返回值，包含一轮扫描的三个层次：

    1. `snapshots`
       原始市场输入。每个元素是一条 `MarketSnapshot`，描述某个交易所、某个标的
       当前的 ticker / funding / liquidity 等信息。

    2. `opportunities`
       由 `snapshots` 经过扫描器筛选、排序后得到的资金费率套利候选。
       这是更接近策略决策的数据。

    3. `output`
       把 `opportunities` 格式化后得到的文本消息，主要用于终端输出、通知或日志。

    一个常见误区是把这三个列表理解成“平行数组”。这里需要明确：

    - `snapshots` 和 `opportunities` 不保证等长
    - `snapshots[i]` 和 `opportunities[i]` 不保证存在对应关系
    - `output` 是由 `opportunities` 逐条格式化得到的，因此当前实现下
      `output[i]` 与 `opportunities[i]` 是对应的

    换句话说：
    - `snapshots` 是输入全集
    - `opportunities` 是从输入中筛出来的结果集
    - `output` 是结果集的人类可读版本
    """

    snapshots: list[MarketSnapshot]  # 本轮扫描拿到的市场快照原始集合
    opportunities: list[FundingOpportunity]  # 从快照中筛选出的资金费率套利机会，通常少于或等于 snapshots
    output: list[str]  # 与 opportunities 对应的文本输出，通常用于日志、终端或通知


class FundingArbRunResult(ArbFrozenModel):
    """一次单交易所资金费率套利运行周期的聚合结果。

    这个对象通常出现在服务层，用来汇总“这一轮运行发生了什么”：
    - `scan`: 本轮扫描阶段的输入与候选输出
    - `opened`: 本轮新开出的仓位
    - `closed`: 本轮被关闭的仓位
    - `active`: 本轮结束后仍然活跃的仓位

    注意这里的几个列表也不是天然同下标对应关系：
    - `opened` / `closed` 是执行动作结果
    - `active` 是运行结束后的最终状态视图
    它们表达的是不同维度的数据，而不是同一批元素的不同列。
    """

    scan: RealtimeScanResult  # 本轮扫描结果，包含快照、机会和文本输出
    opened: list[OpenPositionResult]  # 本轮成功执行的开仓结果
    closed: list[ClosePositionResult]  # 本轮成功执行的平仓结果
    active: list[ActiveFundingArb]  # 本轮结束后仍处于活跃状态的资金费率套利仓位

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        arbitrary_types_allowed=True,
    )


class CrossExchangeRunResult(ArbFrozenModel):
    """一次跨交易所套利运行周期的聚合结果。

    结构上和 `FundingArbRunResult` 类似，只是机会类型与活跃仓位类型不同。
    这个模型用于表达“跨交易所策略这一轮做了什么”，而不是某个单一订单或单一机会。
    """

    snapshots: list[MarketSnapshot]  # 本轮扫描阶段收集到的市场快照
    opportunities: list[CrossExchangeOpportunity]  # 从快照中识别出的跨交易所价差机会
    opened: list[OpenPositionResult]  # 本轮执行后新开的套利仓位结果
    closed: list[ClosePositionResult]  # 本轮执行后平掉的套利仓位结果
    active: list[ActiveCrossExchangeArb]  # 本轮结束后依然存续的跨交易所套利仓位

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        arbitrary_types_allowed=True,
    )


class RecoveryPlan(ArbModel):
    """系统恢复计划。

    当服务重启、崩溃恢复或人工接管时，上层通常需要把多个来源的信息合并起来：
    - 持久化下来的 workflow 状态
    - 实盘交易所返回的真实持仓
    - 实盘交易所返回的未完成订单
    - 对账逻辑给出的差异报告

    这个模型就是把这些恢复所需的信息集中在一起，供恢复流程统一消费。
    """

    workflows: list[WorkflowStateRecord]  # 恢复时已知的 workflow 状态记录
    reconciliation: ReconciliationReport  # 本地状态与交易所实际状态的对账结果
    exchange_positions: list[object] = Field(default_factory=list)  # 从交易所拉回来的原始持仓列表
    exchange_orders: list[object] = Field(default_factory=list)  # 从交易所拉回来的原始活动订单列表

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        arbitrary_types_allowed=True,
    )
