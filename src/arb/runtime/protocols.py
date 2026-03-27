"""运行时协议定义。

这个模块不提供任何具体实现，只定义“某类对象至少要具备什么能力”，
供运行时编排层、烟雾测试层和流式订阅层按需依赖。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from arb.market.schemas import MarketSnapshot
from arb.market.spot_perp_view import SpotPerpSnapshot
from arb.models import MarketType
from arb.schemas.base import SerializableValue


@runtime_checkable
class PublicPingRuntimeProtocol(Protocol):
    """公共连通性检查协议。

    这个协议抽出所有 runtime 都共享的最小公共能力：
    只要对象能检查公共 API 是否可访问，就满足这个协议。

    这样可以避免多个上层协议重复声明同一个 `public_ping()` 方法，
    同时也让协议组合关系更清晰。
    """

    async def public_ping(self) -> bool:
        """检查交易所公共接口是否可访问。"""


@runtime_checkable
class SnapshotRuntimeProtocol(PublicPingRuntimeProtocol, Protocol):
    """实时快照运行时协议。

    任何想被 `RealtimeScanner` / `LiveExchangeManager` 当作“可抓取行情快照”的 runtime，
    至少都需要满足这个接口。

    这里故意只暴露最小能力集合：
    - 公共接口连通性检查
    - 按标的抓取归一化后的市场快照
    """

    async def fetch_public_snapshot(
        self,
        symbol: str,
        market_type: MarketType,
    ) -> MarketSnapshot:
        """抓取指定标的、指定市场的归一化快照。"""


@runtime_checkable
class SpotPerpSnapshotRuntimeProtocol(PublicPingRuntimeProtocol, Protocol):
    """现货/永续成对快照协议。

    这个协议用于 funding arbitrage 这类必须同时看到现货腿和永续腿的场景。
    """

    async def fetch_spot_perp_snapshot(
        self,
        symbol: str,
        *,
        max_age_seconds: float = 3.0,
    ) -> SpotPerpSnapshot:
        """抓取同一交易所、同一标的的现货/永续成对快照。"""


@runtime_checkable
class SmokeRuntimeProtocol(PublicPingRuntimeProtocol, Protocol):
    """烟雾测试运行时协议。

    这个协议服务于 smoke / 健康检查链路，关注的是：
    - 公共 API 能不能连通
    - 私有凭证能不能正常读取账户状态

    它不要求 runtime 一定具备快照抓取能力，因此和 `SnapshotRuntimeProtocol`
    分开定义。
    """

    async def validate_private_access(self) -> dict[str, str]:
        """检查私有 API 凭证是否能正常读取账户信息。"""


@runtime_checkable
class LiveRuntimeProtocol(SnapshotRuntimeProtocol, SmokeRuntimeProtocol, Protocol):
    """完整 live runtime 协议。

    这里通过“协议组合”的方式表达：
    - 既满足实时快照抓取能力
    - 也满足 smoke / 私有凭证检查能力

    这不是在复用实现，而是在声明“完整 runtime 需要同时具备这两组接口”。
    对当前项目里的交易所 runtime 来说，这正好对应一个完整的 live runtime 角色。
    """


@runtime_checkable
class PrivateWsMessageBuilder(Protocol):
    """私有 WS 登录消息构造协议。

    某些运行时场景只需要对象提供私有 websocket 的 endpoint 与认证消息构造能力，
    不需要完整的 runtime 能力，因此单独抽成一个更小的协议。
    """

    # 私有 websocket 连接地址。
    endpoint: str


@runtime_checkable
class SubscribableWsClient(Protocol):
    """公共 WS 订阅协议。

    这个协议描述的是“一个对象是否能帮助流式模块构造订阅消息”，
    通常用于公共行情 websocket 订阅，而不是账户私有流。
    """

    # websocket 连接地址。
    endpoint: str

    def build_subscribe_message(
        self,
        channel: str,
        *,
        symbol: str | None = None,
        market: str | None = None,
    ) -> Mapping[str, SerializableValue]:
        """根据频道、标的和市场信息构造原始订阅消息。"""
