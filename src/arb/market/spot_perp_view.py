"""Spot/perpetual synchronized market view helpers."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import computed_field, model_validator

from arb.market.schemas import MarketSnapshot, coerce_funding_rate, coerce_ticker
from arb.models import FundingRate, MarketType, Ticker
from arb.schemas.base import ArbFrozenModel


def _parse_timestamp(value: str | datetime) -> datetime:
    """把时间戳统一解析成 `datetime` 对象。

    这里兼容两种输入：
    - 已经是 `datetime`：直接返回
    - ISO 格式字符串：解析成 `datetime`
    """

    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


class SpotPerpQuoteView(ArbFrozenModel):
    """现货与永续合约的同步报价视图。

    该模型把同一交易所、同一标的的现货 ticker、永续 ticker 和资金费率捆在一起，
    方便统一做基差、时效性和开平仓条件判断。
    """

    # 视图所属交易所。
    exchange: str
    # 视图所属标的。
    symbol: str
    # 现货侧报价。
    spot_ticker: Ticker
    # 永续侧报价。
    perp_ticker: Ticker
    # 对应永续合约的资金费率信息。
    funding: FundingRate
    # 判断现货与永续报价是否“同步”的最大允许时间差，单位秒。
    max_age_seconds: float = 3.0

    @model_validator(mode="before")
    @classmethod
    def _coerce_inputs(cls, data: object) -> object:
        """在模型校验前把输入统一收敛成标准类型。

        允许调用方直接传字典；这里会把其中的 spot/perp ticker 和 funding
        自动转换成强类型对象，减少外部样板代码。
        """

        if not isinstance(data, dict):
            return data
        payload = dict(data)
        exchange = str(payload.get("exchange", ""))
        symbol = str(payload.get("symbol", ""))
        # 现货腿一律按现货市场解释。
        payload["spot_ticker"] = coerce_ticker(
            payload["spot_ticker"],
            default_exchange=exchange,
            default_symbol=symbol,
            default_market_type=MarketType.SPOT,
        )
        # 永续腿一律按永续市场解释。
        payload["perp_ticker"] = coerce_ticker(
            payload["perp_ticker"],
            default_exchange=exchange,
            default_symbol=symbol,
            default_market_type=MarketType.PERPETUAL,
        )
        # 资金费率也统一做强类型转换，保证下游直接可用。
        payload["funding"] = coerce_funding_rate(
            payload["funding"],
            default_exchange=exchange,
            default_symbol=symbol,
        )
        return payload

    @computed_field(return_type=str)
    @property
    def kind(self) -> str:
        """返回序列化用的模型类型标识。"""

        return "spot_perp_view"

    def basis_bps(self) -> Decimal:
        """计算现货买一到永续卖一的基差，单位 bps。

        对资金费率套利来说，常见的入场视角是“买现货、卖永续”，
        因此这里用 `spot ask` 对 `perp bid` 计算相对价差。
        """

        spot_ask = self.spot_ticker.ask
        perp_bid = self.perp_ticker.bid
        # 现货卖价为 0 时无法计算有效基差，直接返回 0。
        if spot_ask == 0:
            return Decimal("0")
        return ((perp_bid - spot_ask) / spot_ask) * Decimal("10000")

    @computed_field(alias="basis_bps", return_type=Decimal)
    @property
    def basis_bps_value(self) -> Decimal:
        """为序列化暴露 `basis_bps` 字段。"""

        return self.basis_bps()

    def synchronized_within(self, max_age_seconds: float) -> bool:
        """判断现货与永续报价时间戳是否在允许误差内。"""

        spot_ts = _parse_timestamp(self.spot_ticker.ts)
        perp_ts = _parse_timestamp(self.perp_ticker.ts)
        # 只要两条腿的时间差绝对值不超过阈值，就视为同步。
        return abs((perp_ts - spot_ts).total_seconds()) <= max_age_seconds

    @computed_field(alias="synchronized", return_type=bool)
    @property
    def synchronized_value(self) -> bool:
        """基于对象默认阈值输出是否同步的布尔值。"""

        return self.synchronized_within(self.max_age_seconds)


class SpotPerpSnapshot(ArbFrozenModel):
    """现货/永续成对快照。

    除了组合后的 `view`，有时上层还需要保留原始的现货和永续 `MarketSnapshot`，
    这个模型用于把三者一起打包传递。
    """

    # 原始现货快照。
    spot: MarketSnapshot
    # 原始永续快照。
    perp: MarketSnapshot
    # 从两条腿衍生出的统一视图。
    view: SpotPerpQuoteView


def build_spot_perp_view(
    *,
    exchange: str,
    symbol: str,
    spot_ticker: Ticker | dict[str, object],
    perp_ticker: Ticker | dict[str, object],
    funding: FundingRate | dict[str, object],
    max_age_seconds: float = 3.0,
) -> SpotPerpQuoteView:
    """构建一个标准化的 `SpotPerpQuoteView`。

    这是对 `SpotPerpQuoteView(...)` 的便捷封装：
    调用方可以传入强类型对象，也可以传字典，函数会统一做归一化。
    """

    return SpotPerpQuoteView(
        exchange=exchange,
        symbol=symbol,
        # 明确把现货腿解释为 spot ticker。
        spot_ticker=coerce_ticker(
            spot_ticker,
            default_exchange=exchange,
            default_symbol=symbol,
            default_market_type=MarketType.SPOT,
        ),
        # 明确把永续腿解释为 perpetual ticker。
        perp_ticker=coerce_ticker(
            perp_ticker,
            default_exchange=exchange,
            default_symbol=symbol,
            default_market_type=MarketType.PERPETUAL,
        ),
        # funding 也一并归一化，避免外层提前手动构造模型。
        funding=coerce_funding_rate(
            funding,
            default_exchange=exchange,
            default_symbol=symbol,
        ),
        max_age_seconds=max_age_seconds,
    )
