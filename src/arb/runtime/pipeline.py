"""Persistence and output pipeline for realtime scans."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from arb.market.schemas import MarketSnapshot, coerce_market_snapshot
from arb.models import Fill, FundingRate, MarketType, Order, Position, Ticker
from arb.monitoring.metrics import MetricsRegistry
from arb.scanner.funding_scanner import FundingOpportunity
from arb.storage.repository import Repository
from arb.storage.schemas import StoredWorkflowStateRow
from arb.schemas.base import SerializableValue


class MessagePublisher(Protocol):
    """机会消息发布接口。

    `OpportunityPipeline` 不关心消息最终发往哪里，只要求外部实现一个
    `message -> None` 的可调用对象即可，例如打印到终端、推送到 Slack、
    写入消息队列等。
    """

    def __call__(self, message: str) -> None: ...


class OpportunityPipeline:
    """实时扫描结果的持久化与输出管道。

    这个类负责把扫描阶段产出的两类结果统一处理：
    - 市场快照：写入 repository，并更新基础指标
    - 套利机会：格式化为文本消息，并按需要向外发布

    同时它还承接 workflow / order / fill / position 这些运行态事件的落库，
    让上层服务只需要调用统一入口，不需要自己直接操作 repository。
    """

    def __init__(
        self,
        *,
        repository: Repository | None = None,
        metrics: MetricsRegistry | None = None,
        publisher: MessagePublisher | None = None,
    ) -> None:
        self.repository = repository
        self.metrics = metrics or MetricsRegistry()
        self.publisher = publisher

    def process(
        self,
        snapshots: Sequence[MarketSnapshot | Mapping[str, object]],
        opportunities: list[FundingOpportunity],
        *,
        dry_run: bool = False,
    ) -> list[str]:
        """处理一轮扫描输出，并返回格式化后的机会消息列表。

        执行顺序是：
        1. 先持久化行情快照
        2. 再生成并发布机会消息
        3. 最后更新当前轮次的机会数量指标
        """

        # 快照先落库，保证后续分析和排障时能还原本轮输入。
        self.persist_snapshots(snapshots)
        # 将候选机会转成文本输出，并按需推送到外部发布器。
        messages = self.publish_opportunities(opportunities, dry_run=dry_run)
        # 机会数量采用 gauge，因为它表达的是“当前这一轮”的值而非累计值。
        self.metrics.set_gauge("realtime.opportunity_count", Decimal(len(opportunities)))
        return messages

    def persist_snapshots(self, snapshots: Sequence[MarketSnapshot | Mapping[str, object]]) -> None:
        """持久化一批市场快照。

        这里允许上游传入强类型 `MarketSnapshot`，也允许传原始映射对象；
        方法内部会先归一化，再分别抽取 ticker / funding 写入存储层。
        """

        for raw_snapshot in snapshots:
            # 兼容两类输入形状，统一转成标准快照对象。
            snapshot = (
                raw_snapshot
                if isinstance(raw_snapshot, MarketSnapshot)
                else coerce_market_snapshot(dict(raw_snapshot))
            )
            # 每处理一条快照，都累计一次基础监控指标。
            self.metrics.increment("realtime.snapshots")
            ticker = snapshot.ticker
            # ticker 是快照的核心字段，存在 repository 时立即持久化。
            if ticker and self.repository is not None:
                self.repository.save_ticker(ticker)
            funding = snapshot.funding
            # funding 不是每条快照都有，所以需要按存在性判断。
            if funding and self.repository is not None:
                self.repository.save_funding(funding)

    def publish_opportunities(
        self,
        opportunities: list[FundingOpportunity],
        *,
        dry_run: bool = False,
    ) -> list[str]:
        """把套利机会格式化成消息，并可选地向外发布。

        返回值始终是消息字符串列表；即使没有配置 publisher，
        调用方也能直接拿返回值做终端输出或测试断言。
        """

        # 先把每条机会统一转成稳定的文本格式。
        messages = [self.format_opportunity(item, dry_run=dry_run) for item in opportunities]
        if self.publisher is not None:
            # 逐条推送给外部发布器，保持发布接口简单。
            for message in messages:
                self.publisher(message)
        return messages

    def record_workflow_state(
        self,
        *,
        workflow_id: str,
        workflow_type: str,
        exchange: str,
        symbol: str,
        status: str,
        payload: Mapping[str, SerializableValue] | None = None,
    ) -> None:
        """记录 workflow 当前状态。

        这个入口被开仓、平仓、风险监控等多个运行时模块复用，
        用于把 workflow 的最新状态写入存储层，并同步更新 workflow 维度指标。
        """

        # 以状态名为维度累积 workflow 事件计数，便于监控 opening/closed/warning 等状态出现频率。
        self.metrics.increment(f"workflow.{status}")
        if self.repository is not None:
            # 先构造标准化行对象，统一字段形状和时间戳格式。
            record = StoredWorkflowStateRow(
                workflow_id=workflow_id,
                workflow_type=workflow_type,
                exchange=exchange,
                symbol=symbol,
                status=status,
                payload=dict(payload or {}),
                updated_at=datetime.now(UTC).isoformat(),
            )
            if hasattr(self.repository, "save_workflow_state_record"):
                # 新版 repository 直接接受强类型 row，优先走这一条更明确的接口。
                self.repository.save_workflow_state_record(record)
            else:
                # 兼容旧版 repository：拆回关键字参数，避免一次性打断旧调用方。
                self.repository.save_workflow_state(
                    workflow_id=record.workflow_id,
                    workflow_type=record.workflow_type,
                    exchange=record.exchange,
                    symbol=record.symbol,
                    status=record.status,
                    payload=record.payload,
                    updated_at=datetime.fromisoformat(record.updated_at) if record.updated_at else None,
                )

    def record_order(self, order: Order) -> None:
        """记录订单事件。"""

        if self.repository is not None:
            self.repository.save_order(order)

    def record_fill(self, fill: Fill) -> None:
        """记录成交明细事件。"""

        if self.repository is not None:
            self.repository.save_fill(fill)

    def record_position(self, position: Position) -> None:
        """记录持仓快照事件。"""

        if self.repository is not None:
            self.repository.save_position(position)

    def format_opportunity(self, opportunity: FundingOpportunity, *, dry_run: bool = False) -> str:
        """把单条资金费率机会格式化成便于展示和通知的文本。"""

        # dry-run 模式下在前缀显式标识，避免与真实运行输出混淆。
        prefix = "DRY-RUN " if dry_run else ""
        return (
            f"{prefix}{opportunity.exchange} {opportunity.symbol} "
            f"net={opportunity.net_rate} interval={opportunity.funding_interval_hours}h "
            f"annualized={opportunity.annualized_net_rate} "
            f"spread_bps={opportunity.spread_bps} liquidity_usd={opportunity.liquidity_usd}"
        )
