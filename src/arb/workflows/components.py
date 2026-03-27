"""Workflow 共用组件：路由规划与交易所客户端解析。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Generic, Protocol, TypeVar

from arb.execution.router import ExecutionRouter, RouteDecision


@dataclass(slots=True, frozen=True)
class RoutePlanningRequest:
    """一次 workflow 路由规划所需的最小输入。

    这个对象把开仓/平仓 workflow 里共同需要的路由参数集中起来，
    这样上层只需要构造请求对象，不需要直接依赖 `ExecutionRouter` 的参数细节。
    """

    # 首选交易所，通常是当前机会或持仓所在交易所。
    preferred_exchange: str
    # 是否按紧急模式执行；紧急模式通常更偏向 taker 或更激进的路由。
    urgent: bool
    # maker 手续费率，用于比较 maker / taker 成本。
    maker_fee_rate: Decimal
    # taker 手续费率，用于比较 maker / taker 成本。
    taker_fee_rate: Decimal
    # 当前价差，单位 bps，用于辅助决定是否值得走 maker。
    spread_bps: Decimal
    # 首选交易所不可用时的备选交易所。
    fallback_exchange: str | None = None
    # 首选交易所当前是否可用。
    exchange_available: bool = True


class WorkflowRoutePlanner(Protocol):
    """Workflow 级路由规划接口。

    之所以抽成 `Protocol`，是为了让 workflow 只依赖“给我一个路由结果”这个能力，
    而不绑定具体实现。这样后续可以很容易替换成测试桩、特定策略路由器，
    或带更多上下文的高级实现。
    """

    def plan(self, request: RoutePlanningRequest) -> RouteDecision:
        """根据 workflow 请求返回最终执行路由。"""


class DefaultWorkflowRoutePlanner:
    """默认路由规划器。

    当前实现本质上是对 `ExecutionRouter` 的一层薄封装：
    - workflow 侧只关心 `RoutePlanningRequest`
    - 具体的 maker/taker 和交易所选择逻辑仍复用共享的 `ExecutionRouter`

    这样做的目的是把“业务 workflow 参数形状”和“底层路由实现”解耦，
    既减少重复代码，也保留替换实现的空间。
    """

    def __init__(self, router: ExecutionRouter | None = None) -> None:
        # 未显式注入时使用默认路由器，保持调用方零配置可用。
        self.router = router or ExecutionRouter()

    def plan(self, request: RoutePlanningRequest) -> RouteDecision:
        """把 workflow 请求翻译成底层 router 所需参数，并返回路由结果。"""

        return self.router.route(
            preferred_exchange=request.preferred_exchange,
            fallback_exchange=request.fallback_exchange,
            exchange_available=request.exchange_available,
            urgent=request.urgent,
            maker_fee_rate=request.maker_fee_rate,
            taker_fee_rate=request.taker_fee_rate,
            spread_bps=request.spread_bps,
        )


VenueT = TypeVar("VenueT")


class VenueResolver(Protocol[VenueT]):
    """交易所客户端解析接口。

    路由器只会告诉 workflow “本次应该去哪家交易所执行”，
    但真正下单还需要从 `venue_clients` 里取出对应的 client bundle。
    这个接口就是把“路由结果 -> venue 对象”的解析步骤显式抽出来。
    """

    def resolve(self, venue_clients: Mapping[str, VenueT], exchange: str) -> VenueT | None:
        """根据交易所标识返回对应的 venue bundle。"""


class DefaultVenueResolver(Generic[VenueT]):
    """默认 venue 解析器。

    默认实现非常直接：把 `exchange` 当成键，直接从 `venue_client_bundle` 映射里取值。
    这已经覆盖了大多数场景；如果以后需要 alias、降级映射或按区域选路，
    可以替换成自定义实现，而不需要改 workflow 主流程。
    """

    def resolve(self, venue_clients: Mapping[str, VenueT], exchange: str) -> VenueT | None:
        """从映射中解析当前路由命中的 venue。"""

        return venue_clients.get(exchange)
