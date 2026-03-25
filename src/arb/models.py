"""Shared domain models."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum

from pydantic import Field, computed_field

from arb.funding import DEFAULT_FUNDING_INTERVAL_HOURS
from arb.schemas.base import ArbFrozenModel


def utc_now() -> datetime:
    """返回当前 UTC 时间。

    领域模型里的时间戳默认统一采用 UTC，避免不同机器或时区设置导致的歧义。
    """

    return datetime.now(tz=timezone.utc)


class MarketType(StrEnum):
    """市场类型枚举。"""

    # 现货市场。
    SPOT = "spot"
    # 永续合约市场。
    PERPETUAL = "perpetual"


class Side(StrEnum):
    """买卖方向枚举。"""

    # 买入方向。
    BUY = "buy"
    # 卖出方向。
    SELL = "sell"


class OrderStatus(StrEnum):
    """订单状态枚举。

    该枚举用于把不同交易所的订单生命周期收敛成统一表达。
    """

    # 订单已创建，但尚未成交。
    NEW = "new"
    # 订单已部分成交，仍可能继续成交。
    PARTIALLY_FILLED = "partially_filled"
    # 订单已全部成交。
    FILLED = "filled"
    # 订单已取消。
    CANCELED = "canceled"
    # 订单被交易所拒绝。
    REJECTED = "rejected"
    # 订单过期失效。
    EXPIRED = "expired"


class PositionDirection(StrEnum):
    """持仓方向枚举。"""

    # 多头持仓。
    LONG = "long"
    # 空头持仓。
    SHORT = "short"


class Ticker(ArbFrozenModel):
    """基础行情报价模型。

    用于表达某个交易所、某个市场、某个标的在某个时间点的买一卖一和最新成交价。
    """

    # 行情来源交易所。
    exchange: str
    # 交易标的，例如 BTC/USDT 或 BTCUSDT。
    symbol: str
    # 行情所属市场类型，例如现货或永续合约。
    market_type: MarketType
    # 当前最佳买价。
    bid: Decimal
    # 当前最佳卖价。
    ask: Decimal
    # 最近成交价或归一化后的最新价格。
    last: Decimal
    # 行情时间戳，默认使用当前 UTC 时间。
    ts: datetime = Field(default_factory=utc_now)

    @computed_field(return_type=str)
    @property
    def kind(self) -> str:
        """返回序列化用的模型类型标识。"""

        return "ticker"


class OrderBookLevel(ArbFrozenModel):
    """订单簿单档报价模型。"""

    # 该档位的价格。
    price: Decimal
    # 该档位的挂单数量。
    size: Decimal


class OrderBook(ArbFrozenModel):
    """订单簿快照模型。

    该模型保存一组买盘和卖盘档位，通常用于估算滑点、流动性和盘口深度。
    """

    # 订单簿来源交易所。
    exchange: str
    # 交易标的。
    symbol: str
    # 订单簿所属市场类型。
    market_type: MarketType
    # 买盘档位列表，通常按价格从高到低排列。
    bids: tuple[OrderBookLevel, ...]
    # 卖盘档位列表，通常按价格从低到高排列。
    asks: tuple[OrderBookLevel, ...]
    # 快照时间戳。
    ts: datetime = Field(default_factory=utc_now)

    @computed_field(return_type=str)
    @property
    def kind(self) -> str:
        """返回序列化用的模型类型标识。"""

        return "orderbook"


class FundingRate(ArbFrozenModel):
    """资金费率模型。

    主要用于永续合约场景，描述当前资金费率、下一次结算时间以及预测值等信息。
    """

    # 资金费率所属交易所。
    exchange: str
    # 资金费率所属标的。
    symbol: str
    # 当前资金费率。
    rate: Decimal
    # 下一次资金费结算时间。
    next_funding_time: datetime
    # 预测资金费率；有些交易所会提供，有些不会。
    predicted_rate: Decimal | None = None
    # 资金费率结算周期，单位小时，至少为 1。
    funding_interval_hours: int = Field(default=DEFAULT_FUNDING_INTERVAL_HOURS, ge=1)
    # 这条资金费率记录的采集时间。
    ts: datetime = Field(default_factory=utc_now)

    @computed_field(return_type=str)
    @property
    def kind(self) -> str:
        """返回序列化用的模型类型标识。"""

        return "funding"


class Order(ArbFrozenModel):
    """统一订单模型。

    该模型用于表达策略或执行层视角下的一笔订单，包括目标数量、成交情况、
    状态、价格信息以及交易所原始状态映射结果。
    """

    # 下单交易所。
    exchange: str
    # 下单标的。
    symbol: str
    # 下单市场类型。
    market_type: MarketType
    # 买卖方向。
    side: Side
    # 订单总数量。
    quantity: Decimal
    # 限价单价格；市价单等场景下可能为空。
    price: Decimal | None
    # 归一化后的订单状态。
    status: OrderStatus
    # 交易所订单 ID。
    order_id: str | None = None
    # 客户端自定义订单 ID，便于幂等和追踪。
    client_order_id: str | None = None
    # 当前累计已成交数量。
    filled_quantity: Decimal = Decimal("0")
    # 平均成交价；未成交时可能为空。
    average_price: Decimal | None = None
    # 是否仅减仓。
    reduce_only: bool = False
    # 交易所原始状态字符串，便于调试和排障。
    raw_status: str | None = None
    # 订单记录时间戳。
    ts: datetime = Field(default_factory=utc_now)

    @property
    def remaining_quantity(self) -> Decimal:
        """返回订单剩余未成交数量。

        即使出现异常数据导致 `filled_quantity` 大于 `quantity`，
        这里也会通过 `max(..., 0)` 保证结果不为负数。
        """

        return max(self.quantity - self.filled_quantity, Decimal("0"))


class Fill(ArbFrozenModel):
    """成交明细模型。

    一笔订单可能拆成多笔成交，`Fill` 用于记录其中每一笔实际成交的信息。
    """

    # 成交发生的交易所。
    exchange: str
    # 成交所属标的。
    symbol: str
    # 成交所属市场类型。
    market_type: MarketType
    # 成交方向。
    side: Side
    # 本次成交数量。
    quantity: Decimal
    # 本次成交价格。
    price: Decimal
    # 对应的订单 ID。
    order_id: str
    # 成交 ID，用于区分同一订单下的不同 fill。
    fill_id: str
    # 手续费金额。
    fee: Decimal = Decimal("0")
    # 手续费资产，例如 USDT、BNB。
    fee_asset: str | None = None
    # 流动性类型，例如 maker / taker。
    liquidity: str | None = None
    # 成交时间戳。
    ts: datetime = Field(default_factory=utc_now)


class Position(ArbFrozenModel):
    """统一持仓模型。

    用于描述某个交易所、某个市场中的一笔持仓，包括方向、数量、
    开仓成本、标记价格、未实现盈亏以及杠杆等附加信息。
    """

    # 持仓所在交易所。
    exchange: str
    # 持仓标的。
    symbol: str
    # 持仓所属市场类型。
    market_type: MarketType
    # 持仓方向，多头或空头。
    direction: PositionDirection
    # 当前持仓数量。
    quantity: Decimal
    # 开仓均价或建仓成本价。
    entry_price: Decimal
    # 当前标记价格，用于估算盈亏和风险。
    mark_price: Decimal
    # 未实现盈亏。
    unrealized_pnl: Decimal = Decimal("0")
    # 强平价格；并非所有市场都会提供。
    liquidation_price: Decimal | None = None
    # 杠杆倍数；现货场景通常为空。
    leverage: Decimal | None = None
    # 保证金模式，例如 cross / isolated。
    margin_mode: str | None = None
    # 交易所内部的持仓 ID；有些交易所可能没有。
    position_id: str | None = None
    # 持仓快照时间戳。
    ts: datetime = Field(default_factory=utc_now)
