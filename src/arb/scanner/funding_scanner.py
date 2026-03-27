"""资金费率套利机会扫描器。

这个模块负责把上游收集到的标准化市场快照 `MarketSnapshot`
转换成可用于策略决策的 `FundingOpportunity` 列表。

整体流程可以概括为三步：

1. 归一化输入
   - 调用方既可以传入已经构造好的 `MarketSnapshot`
   - 也可以传入字典形态的数据
   - 扫描器内部会统一转换成强类型对象

2. 从快照中提炼套利机会
   - 读取资金费率 `funding.rate` 作为毛收益率 `gross_rate`
   - 扣除手续费、滑点、借币成本、划转成本后得到 `net_rate`
   - 结合盘口 bid / ask 估算价差成本与可成交流动性
   - 把结算周期收益换算成小时、日、年化维度，便于横向比较

3. 过滤与排序
   - 过滤掉净收益率不足、流动性不足、不在白名单或命中黑名单的候选
   - 按 `annualized_net_rate` 从高到低排序，优先返回更高收益机会

注意：
- 这里扫描的是“候选机会”，不是执行结果
- 返回列表中的元素之间彼此独立，不保证和输入快照列表一一对应
- 费率字段使用的是比例值，例如 `0.0005` 表示 `0.05%`
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal

from arb.funding import DEFAULT_FUNDING_INTERVAL_HOURS
from arb.market.schemas import (
    MarketSnapshot,
    coerce_market_snapshot,
    coerce_orderbook,
    coerce_ticker,
)
from arb.models import MarketType, OrderBook, Ticker
from arb.schemas.base import ArbFrozenModel, SerializableValue

from arb.scanner.cost_model import annualize_rate, daily_rate, estimate_net_rate, hourly_rate
from arb.scanner.depth import estimate_fill_for_quantity, estimate_max_fill_for_slippage
from arb.scanner.filters import filter_opportunities


class EntryCapacity(ArbFrozenModel):
    """同一机会在当前订单簿约束下可接受的最大入场容量。"""

    quantity: Decimal = Decimal("0")
    notional_usd: Decimal = Decimal("0")
    buy_vwap: Decimal | None = None
    sell_vwap: Decimal | None = None
    buy_slippage_bps: Decimal = Decimal("0")
    sell_slippage_bps: Decimal = Decimal("0")


class FundingOpportunity(ArbFrozenModel):
    """单个资金费率套利候选机会。

    这个模型不是原始行情，而是扫描器对原始快照做了一轮收益和成本计算后的结果。
    它表达的核心问题是：
    “对于某个交易所、某个标的，当前做一组 funding arbitrage 值不值得？”

    字段可以按几类理解：

    1. 标识字段
       - `exchange`
       - `symbol`

    2. 原始/净化后的收益字段
       - `gross_rate`: 原始资金费率
       - `net_rate`: 扣除成本后的净资金费率

    3. 统一周期后的收益字段
       - `hourly_net_rate`
       - `daily_net_rate`
       - `annualized_net_rate`

    4. 交易可行性字段
       - `spread_bps`: 当前盘口买卖价差，越大通常越不利
       - `liquidity_usd`: 粗略估计的可成交美元流动性
    """

    exchange: str
    symbol: str
    gross_rate: Decimal  # 原始资金费率，直接来自 snapshot.funding.rate
    net_rate: Decimal  # 扣除手续费、滑点、借币和划转等成本后的净费率
    funding_interval_hours: int = DEFAULT_FUNDING_INTERVAL_HOURS  # 资金费率结算周期，常见为 8 小时
    hourly_net_rate: Decimal = Decimal("0")  # 将 net_rate 按结算周期折算成每小时收益率
    daily_net_rate: Decimal = Decimal("0")  # 将 net_rate 折算成每天收益率，便于跨交易所比较
    annualized_net_rate: Decimal  # 将 net_rate 折算成年化收益率，用于排序展示
    spread_bps: Decimal  # 当前盘口价差，单位 bps；越大通常意味着冲击成本越高
    liquidity_usd: Decimal  # 估算流动性，优先使用快照显式值，否则退化为 ask * top_ask_size
    capacity_quantity: Decimal = Decimal("0")  # 在当前订单簿深度与滑点限制下，建议的最大开仓数量
    capacity_notional_usd: Decimal = Decimal("0")  # 与 capacity_quantity 对应的保守名义资金容量
    spot_entry_price: Decimal = Decimal("0")  # 现货腿实际入场参考价；完整模式下优先使用现货 VWAP
    perp_entry_price: Decimal = Decimal("0")  # 永续腿实际入场参考价；完整模式下优先使用永续 VWAP
    entry_basis_bps: Decimal = Decimal("0")  # 以实际入场参考价计算的 spot/perp 基差
    pair_mode: bool = False  # 是否来自真实的现货/永续双腿视图；basis 过滤仅对这种机会生效


class FundingScanner:
    """基于标准化市场快照扫描资金费率套利机会。

    这个类只负责“识别机会”，不负责：
    - 下单
    - 持仓管理
    - 风险控制
    - 状态持久化

    它的输入是一批市场快照，输出是经过计算、过滤、排序后的套利候选列表。
    """

    def __init__(
        self,
        *,
        trading_fee_rate: Decimal = Decimal("0"),
        slippage_rate: Decimal = Decimal("0"),
        borrow_rate: Decimal = Decimal("0"),
        transfer_rate: Decimal = Decimal("0"),
        min_net_rate: Decimal = Decimal("0"),
        min_liquidity_usd: Decimal = Decimal("0"),
        max_entry_basis_bps: Decimal | None = Decimal("25"),
        max_orderbook_slippage_bps: Decimal = Decimal("0"),
        max_orderbook_levels: int | None = 1,
        whitelist: set[str] | None = None,
        blacklist: set[str] | None = None,
    ) -> None:
        """初始化扫描器参数。

        这些参数本质上分为两组：

        1. 成本参数
           用于把原始 funding rate 转成更接近真实收益的 net rate：
           - `trading_fee_rate`: 手续费率
           - `slippage_rate`: 滑点成本
           - `borrow_rate`: 借币或持币成本
           - `transfer_rate`: 划转或调仓相关成本

        2. 过滤参数
           用于控制哪些候选会被保留下来：
           - `min_net_rate`: 最低净收益率门槛
           - `min_liquidity_usd`: 最低流动性门槛
           - `max_entry_basis_bps`: 允许的最大双腿入场基差；超出后直接过滤
           - `max_orderbook_slippage_bps`: 订单簿深度估算允许的最大 VWAP 滑点
           - `max_orderbook_levels`: 深度估算最多消费多少档盘口；`None` 表示不限制
           - `whitelist`: 若设置，则只有列表内 symbol 会被保留
           - `blacklist`: 若设置，则列表内 symbol 会被剔除
        """

        self.trading_fee_rate = trading_fee_rate
        self.slippage_rate = slippage_rate
        self.borrow_rate = borrow_rate
        self.transfer_rate = transfer_rate
        self.min_net_rate = min_net_rate
        self.min_liquidity_usd = min_liquidity_usd
        self.max_entry_basis_bps = max_entry_basis_bps
        self.max_orderbook_slippage_bps = max_orderbook_slippage_bps
        self.max_orderbook_levels = max_orderbook_levels
        self.whitelist = whitelist
        self.blacklist = blacklist

    def scan(
        self,
        snapshots: Sequence[MarketSnapshot | Mapping[str, SerializableValue]],
    ) -> list[FundingOpportunity]:
        """扫描一批市场快照，并返回排序后的资金费率机会列表。

        输入是“原始快照集合”，输出是“候选机会集合”，两者不是平行数组关系。
        常见情况是：
        - 输入有 100 条快照
        - 其中只有 20 条带 funding 信息
        - 最终只有 5 条满足最小净收益和流动性要求

        因此：
        - 返回结果数量通常小于输入数量
        - 返回结果顺序是按年化收益率重新排序后的顺序
        - 不应依赖 `snapshots[i]` 与返回值 `result[i]` 的下标对应关系
        """

        candidates: list[FundingOpportunity] = []
        for raw_snapshot in snapshots:
            # 调用方既可能传入强类型对象，也可能传入字典；
            # 这里统一转成 `MarketSnapshot`，让后续逻辑只处理一种输入形状。
            snapshot = self._coerce_snapshot(raw_snapshot)
            funding = snapshot.funding
            ticker = snapshot.ticker
            # 资金费率套利必须同时依赖 funding 和基础行情；
            # 缺任一关键字段，就无法计算有效机会。
            if not funding or not ticker:
                continue

            # 原始收益率直接取资金费率本身。
            gross_rate = funding.rate
            interval_hours = funding.funding_interval_hours
            # 净收益率 = 毛收益率 - 各类显式成本。
            # 这里只是静态估算，不代表真实成交后的精确收益。
            net_rate = estimate_net_rate(
                gross_rate,
                trading_fee_rate=self.trading_fee_rate,
                slippage_rate=self.slippage_rate,
                borrow_rate=self.borrow_rate,
                transfer_rate=self.transfer_rate,
            )

            # 盘口价差使用 bid / ask 计算。
            # 这里的 spread_bps 主要用于表达“当前交易成本大不大”，
            # 不是 funding spread，也不是跨交易所价差。
            bid = ticker.bid
            ask = ticker.ask
            mid = (bid + ask) / Decimal("2")
            spread_bps = ((ask - bid) / mid) * Decimal("10000") if mid else Decimal("0")

            # 先尝试基于订单簿两侧深度估算“这轮机会到底能做多大”。
            # 若快照没有 orderbook，再回退到旧的顶档流动性近似。
            capacity = self._entry_capacity(snapshot)
            liquidity_usd = capacity.notional_usd
            spot_entry_price, perp_entry_price = self._entry_prices(snapshot, capacity)
            entry_basis_bps = self._basis_bps(spot_entry_price, perp_entry_price)
            pair_mode = self._has_pair_view(snapshot)

            # 将单个快照转换成统一的机会对象。
            # 注意这些 rate 都是比例值，不是百分数字符串。
            opportunity = FundingOpportunity(
                exchange=funding.exchange,
                symbol=funding.symbol,
                gross_rate=gross_rate,
                net_rate=net_rate,
                funding_interval_hours=interval_hours,
                # 同一标的在不同交易所可能有不同 funding 结算周期，
                # 所以这里统一换算成小时、日、年化后再比较更合理。
                hourly_net_rate=hourly_rate(net_rate, interval_hours=interval_hours),
                daily_net_rate=daily_rate(net_rate, interval_hours=interval_hours),
                annualized_net_rate=annualize_rate(net_rate, interval_hours=interval_hours),
                spread_bps=spread_bps,
                liquidity_usd=liquidity_usd,
                capacity_quantity=capacity.quantity,
                capacity_notional_usd=capacity.notional_usd,
                spot_entry_price=spot_entry_price,
                perp_entry_price=perp_entry_price,
                entry_basis_bps=entry_basis_bps,
                pair_mode=pair_mode,
            )
            candidates.append(opportunity)

        # 过滤步骤把“数学上可算”的候选，进一步收敛成“策略上愿意看”的候选。
        filtered = filter_opportunities(
            candidates,
            min_net_rate=self.min_net_rate,
            min_liquidity_usd=self.min_liquidity_usd,
            max_entry_basis_bps=self.max_entry_basis_bps,
            whitelist=self.whitelist,
            blacklist=self.blacklist,
        )
        # 最终按年化净收益率从高到低排序。
        # 这是展示和挑选机会时最直观的排序方式之一。
        return sorted(filtered, key=lambda item: item.annualized_net_rate, reverse=True)

    @staticmethod
    def _coerce_snapshot(
        snapshot: MarketSnapshot | Mapping[str, SerializableValue],
    ) -> MarketSnapshot:
        """把输入统一转换成 `MarketSnapshot`。

        这是一个非常小但很关键的兼容层：
        - 如果上游已经构造好了 `MarketSnapshot`，直接复用
        - 如果上游传的是字典，则委托 `coerce_market_snapshot()` 做结构化转换

        这样 `scan()` 主流程就不需要在每一步都判断输入类型。
        """

        if isinstance(snapshot, MarketSnapshot):
            return snapshot
        return coerce_market_snapshot(dict(snapshot))

    def _entry_capacity(self, snapshot: MarketSnapshot) -> EntryCapacity:
        """估算当前快照在订单簿约束下的最大可入场容量。

        完整模式下优先使用成对视图中的：
        - `spot_orderbook.asks` 计算现货买入容量
        - `perp_orderbook.bids` 计算永续卖出容量

        若成对视图缺失，则回退到单快照模式，保持旧调用方兼容。
        """

        spot_orderbook = self._spot_orderbook(snapshot)
        perp_orderbook = self._perp_orderbook(snapshot)
        if spot_orderbook is None or perp_orderbook is None:
            return self._single_snapshot_entry_capacity(snapshot)

        buy_capacity = estimate_max_fill_for_slippage(
            spot_orderbook,
            side="buy",
            max_slippage_bps=self.max_orderbook_slippage_bps,
            max_levels=self.max_orderbook_levels,
        )
        sell_capacity = estimate_max_fill_for_slippage(
            perp_orderbook,
            side="sell",
            max_slippage_bps=self.max_orderbook_slippage_bps,
            max_levels=self.max_orderbook_levels,
        )
        quantity = min(buy_capacity.quantity, sell_capacity.quantity)
        if quantity <= 0:
            return self._fallback_entry_capacity(snapshot)

        # 两侧各自先估算最大可成交量，再回头按共同数量重算 VWAP。
        # 这里必须分别用现货 asks 与永续 bids 重算，才能得到真实 pair 的入场价。
        buy_fill = estimate_fill_for_quantity(
            spot_orderbook,
            side="buy",
            quantity=quantity,
            max_levels=self.max_orderbook_levels,
        )
        sell_fill = estimate_fill_for_quantity(
            perp_orderbook,
            side="sell",
            quantity=quantity,
            max_levels=self.max_orderbook_levels,
        )
        return EntryCapacity(
            quantity=quantity,
            notional_usd=min(buy_fill.notional, sell_fill.notional),
            buy_vwap=buy_fill.vwap,
            sell_vwap=sell_fill.vwap,
            buy_slippage_bps=buy_fill.slippage_bps,
            sell_slippage_bps=sell_fill.slippage_bps,
        )

    def _single_snapshot_entry_capacity(self, snapshot: MarketSnapshot) -> EntryCapacity:
        """在缺少成对视图时，回退到单快照模式。"""

        orderbook = snapshot.orderbook
        if orderbook is None:
            return self._fallback_entry_capacity(snapshot)

        buy_capacity = estimate_max_fill_for_slippage(
            orderbook,
            side="buy",
            max_slippage_bps=self.max_orderbook_slippage_bps,
            max_levels=self.max_orderbook_levels,
        )
        sell_capacity = estimate_max_fill_for_slippage(
            orderbook,
            side="sell",
            max_slippage_bps=self.max_orderbook_slippage_bps,
            max_levels=self.max_orderbook_levels,
        )
        quantity = min(buy_capacity.quantity, sell_capacity.quantity)
        if quantity <= 0:
            return self._fallback_entry_capacity(snapshot)
        buy_fill = estimate_fill_for_quantity(
            orderbook,
            side="buy",
            quantity=quantity,
            max_levels=self.max_orderbook_levels,
        )
        sell_fill = estimate_fill_for_quantity(
            orderbook,
            side="sell",
            quantity=quantity,
            max_levels=self.max_orderbook_levels,
        )
        return EntryCapacity(
            quantity=quantity,
            notional_usd=min(buy_fill.notional, sell_fill.notional),
            buy_vwap=buy_fill.vwap,
            sell_vwap=sell_fill.vwap,
            buy_slippage_bps=buy_fill.slippage_bps,
            sell_slippage_bps=sell_fill.slippage_bps,
        )

    @staticmethod
    def _fallback_entry_capacity(snapshot: MarketSnapshot) -> EntryCapacity:
        """在缺少订单簿深度时，回退到顶档近似。"""

        ask = snapshot.ticker.ask
        quantity = snapshot.top_ask_size or Decimal("0")
        notional = snapshot.liquidity_usd
        if notional is None:
            notional = ask * quantity
        if quantity <= 0 and ask > 0 and notional > 0:
            quantity = notional / ask
        return EntryCapacity(
            quantity=quantity,
            notional_usd=notional,
            buy_vwap=ask if quantity > 0 else None,
            sell_vwap=snapshot.ticker.bid if quantity > 0 else None,
        )

    def _entry_prices(self, snapshot: MarketSnapshot, capacity: EntryCapacity) -> tuple[Decimal, Decimal]:
        """返回现货腿/永续腿的实际入场参考价。"""

        spot_ticker = self._spot_ticker(snapshot)
        perp_ticker = self._perp_ticker(snapshot)
        spot_price = capacity.buy_vwap or (spot_ticker.ask if spot_ticker is not None else snapshot.ticker.ask)
        perp_price = capacity.sell_vwap or (perp_ticker.bid if perp_ticker is not None else snapshot.ticker.bid)
        return spot_price, perp_price

    @staticmethod
    def _basis_bps(spot_price: Decimal, perp_price: Decimal) -> Decimal:
        if spot_price <= 0:
            return Decimal("0")
        return ((perp_price - spot_price) / spot_price) * Decimal("10000")

    @staticmethod
    def _spot_ticker(snapshot: MarketSnapshot) -> Ticker | None:
        view_payload = snapshot.view
        if not isinstance(view_payload, Mapping):
            return None
        spot_payload = view_payload.get("spot_ticker")
        return (
            coerce_ticker(dict(spot_payload), default_market_type=MarketType.SPOT)
            if isinstance(spot_payload, Mapping)
            else None
        )

    @staticmethod
    def _perp_ticker(snapshot: MarketSnapshot) -> Ticker | None:
        view_payload = snapshot.view
        if not isinstance(view_payload, Mapping):
            return None
        perp_payload = view_payload.get("perp_ticker")
        if isinstance(perp_payload, Mapping):
            return coerce_ticker(dict(perp_payload), default_market_type=MarketType.PERPETUAL)
        return snapshot.ticker

    @staticmethod
    def _spot_orderbook(snapshot: MarketSnapshot) -> OrderBook | None:
        view_payload = snapshot.view
        if not isinstance(view_payload, Mapping):
            return None
        orderbook_payload = view_payload.get("spot_orderbook")
        return coerce_orderbook(dict(orderbook_payload)) if isinstance(orderbook_payload, Mapping) else None

    @staticmethod
    def _perp_orderbook(snapshot: MarketSnapshot) -> OrderBook | None:
        view_payload = snapshot.view
        if not isinstance(view_payload, Mapping):
            return snapshot.orderbook
        orderbook_payload = view_payload.get("perp_orderbook")
        if isinstance(orderbook_payload, Mapping):
            return coerce_orderbook(dict(orderbook_payload))
        return snapshot.orderbook

    @staticmethod
    def _has_pair_view(snapshot: MarketSnapshot) -> bool:
        view_payload = snapshot.view
        return (
            isinstance(view_payload, Mapping)
            and isinstance(view_payload.get("spot_ticker"), Mapping)
            and isinstance(view_payload.get("perp_ticker"), Mapping)
        )
