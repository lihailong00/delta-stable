"""Typed market snapshot and event models."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Literal

from arb.funding import DEFAULT_FUNDING_INTERVAL_HOURS
from arb.models import FundingRate, MarketType, OrderBook, Ticker, utc_now
from arb.schemas.base import ArbFrozenModel, SerializableValue


class NormalizedWsEvent(ArbFrozenModel):
    """归一化后的 WebSocket 事件模型。

    不同交易所的原始 WS 消息格式差异很大，这个模型用于把消息收敛成统一形状，
    便于后续日志记录、调试、回放和跨交易所处理。
    """

    kind: Literal["ws_event"] = "ws_event"
    # 事件来源交易所，例如 binance / okx。
    exchange: str
    # 事件所属频道，例如 ticker / orderbook / funding。
    channel: str
    # 归一化后的事件正文，要求值可序列化，便于持久化和传输。
    payload: dict[str, SerializableValue]
    # 本地接收到该事件的时间戳。
    received_at: datetime


class MarketSnapshot(ArbFrozenModel):
    """统一的市场快照模型。

    一个快照通常至少包含 ticker，必要时还可以附带 orderbook、funding、
    流动性估计和盘口顶部可成交量等补充信息。
    """

    # 行情基础报价，通常是后续计算和策略判断的核心输入。
    ticker: Ticker
    # 可选的订单簿快照；并非所有场景都会携带。
    orderbook: OrderBook | None = None
    # 可选的资金费率信息，永续合约场景下尤为关键。
    funding: FundingRate | None = None
    # 可选的现货/永续配对视图；当上游已经算好 basis 所需的双腿报价时可直接复用。
    view: dict[str, SerializableValue] | None = None
    # 估算出的美元流动性，用于过滤过于冷门的标的。
    liquidity_usd: Decimal | None = None
    # 顶部卖一档的可成交数量，常用于评估冲击成本。
    top_ask_size: Decimal | None = None


def coerce_ticker(
    payload: Ticker | dict[str, object],
    *,
    default_exchange: str | None = None,
    default_symbol: str | None = None,
    default_market_type: MarketType = MarketType.PERPETUAL,
    default_ts: datetime | None = None,
) -> Ticker:
    """把输入统一转换成 `Ticker` 对象。

    支持两类输入：
    - 已经是 `Ticker`：直接返回
    - 是字典：自动补齐缺失字段，再做模型校验

    这个函数的目标是尽量吸收上游数据的不完整性，让下游总能拿到结构完整的 ticker。
    """

    if isinstance(payload, Ticker):
        return payload
    data = dict(payload)
    # 外层 schema 的 kind 字段不属于 Ticker 本身，校验前移除。
    data.pop("kind", None)
    # 若上游未传 exchange / symbol，则使用调用方提供的默认值兜底。
    data.setdefault("exchange", default_exchange or "")
    data.setdefault("symbol", default_symbol or "")
    # 市场类型默认按永续合约处理；调用方可显式覆盖。
    data.setdefault("market_type", default_market_type.value)
    # 只给出 bid/ask 或 last 时，尽量互相补齐，保证基础报价字段完整。
    data.setdefault("last", data.get("ask", data.get("bid", "0")))
    data.setdefault("bid", data.get("last", "0"))
    data.setdefault("ask", data.get("last", data.get("bid", "0")))
    # 没有时间戳时，用默认时间或当前 UTC 时间补齐。
    data.setdefault("ts", (default_ts or utc_now()).isoformat())
    return Ticker.model_validate(data)


def coerce_funding_rate(
    payload: FundingRate | dict[str, object],
    *,
    default_exchange: str | None = None,
    default_symbol: str | None = None,
    default_ts: datetime | None = None,
) -> FundingRate:
    """把输入统一转换成 `FundingRate` 对象。

    该函数主要用于兼容不同来源的资金费率数据命名差异，
    例如 `fundingIntervalHours` 这类外部字段名也会被自动吸收。
    """

    if isinstance(payload, FundingRate):
        return payload
    data = dict(payload)
    # 归一化前先移除外层 kind，避免影响 FundingRate 校验。
    data.pop("kind", None)
    # 资金费率记录通常要求时间字段一致，因此这里先确定一个统一 timestamp。
    timestamp = str(data.get("ts", (default_ts or utc_now()).isoformat()))
    data.setdefault("exchange", default_exchange or "")
    data.setdefault("symbol", default_symbol or "")
    # 未显式提供 predicted_rate 时，默认使用当前 rate。
    data.setdefault("predicted_rate", data.get("rate"))
    # 兼容 camelCase 字段；缺失时回落到系统默认资金费率周期。
    data.setdefault("funding_interval_hours", data.get("fundingIntervalHours", DEFAULT_FUNDING_INTERVAL_HOURS))
    # 下一次资金费结算时间默认沿用当前时间戳，至少保证字段完整。
    data.setdefault("next_funding_time", timestamp)
    data.setdefault("ts", timestamp)
    return FundingRate.model_validate(data)


def coerce_market_snapshot(snapshot: MarketSnapshot | dict[str, object]) -> MarketSnapshot:
    """把输入统一转换成 `MarketSnapshot`。

    这个函数会递归处理内部的 `ticker` 和 `funding`：
    - `funding` 如果是字典，会先转成 `FundingRate`
    - `ticker` 如果是字典，会结合 funding 中的信息自动补默认值

    如果 `ticker` 既不是字典也不是合法 `Ticker` 输入，会直接抛出异常。
    """

    if isinstance(snapshot, MarketSnapshot):
        return snapshot
    payload = dict(snapshot)
    funding_payload = payload.get("funding")
    # funding 允许缺失；若存在且是字典，则先归一化成 FundingRate。
    funding = (
        coerce_funding_rate(funding_payload) if isinstance(funding_payload, dict) else funding_payload
    )
    ticker_payload = payload.get("ticker")
    # ticker 是快照的必备部分，因此这里严格要求它可被转换。
    if not isinstance(ticker_payload, dict):
        raise TypeError("snapshot.ticker must be a mapping or Ticker")
    # 如果 funding 已经存在，则优先复用其中的 exchange / symbol / ts 作为 ticker 默认值。
    ticker = coerce_ticker(
        ticker_payload,
        default_exchange=funding.exchange if isinstance(funding, FundingRate) else None,
        default_symbol=funding.symbol if isinstance(funding, FundingRate) else None,
        default_market_type=MarketType.PERPETUAL,
        default_ts=funding.ts if isinstance(funding, FundingRate) else None,
    )
    liquidity_value = payload.get("liquidity_usd")
    top_ask_size_value = payload.get("top_ask_size")
    view_payload = payload.get("view")
    # 数值字段统一通过 Decimal(str(...)) 转换，避免浮点精度问题。
    return MarketSnapshot(
        ticker=ticker,
        funding=funding if isinstance(funding, FundingRate) else None,
        view=dict(view_payload) if isinstance(view_payload, Mapping) else None,
        liquidity_usd=Decimal(str(liquidity_value)) if liquidity_value is not None else None,
        top_ask_size=Decimal(str(top_ask_size_value)) if top_ask_size_value is not None else None,
    )
