"""健康检查辅助工具。

这个模块实现的是一套非常轻量的“心跳式存活检查”：
- 某个组件在成功完成一次关键动作后，上报一次 heartbeat
- 系统记录该组件最近一次活跃时间
- 如果长时间没有新的 heartbeat，则判定该组件已经 stale / unhealthy

它当前并不追踪复杂的健康维度，例如错误原因、重试次数、响应延迟等；
核心目标只是回答一个问题：某个组件最近是否还在正常工作。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum


def utc_now() -> datetime:
    """返回带 UTC 时区的当前时间。

    统一由这里生成当前时间，便于测试中注入固定时间，也避免不同模块
    各自调用 `datetime.now()` 时产生的时区不一致问题。
    """

    return datetime.now(tz=timezone.utc)


class ComponentKind(StrEnum):
    """组件类别。

    这里不直接把整个组件标识建成一个大枚举，而是只约束“组件属于哪一类”，
    例如交易所 runtime、websocket 连接等；组件名称本身仍然保持字符串，
    以避免枚举随着交易所数量不断膨胀。
    """

    EXCHANGE = "exchange"
    WS = "ws"


@dataclass(slots=True, frozen=True)
class ComponentKey:
    """组件唯一标识。

    一个组件由两部分组成：
    - `kind`：组件类别，例如交易所或 websocket
    - `name`：该类别下的具体名称，例如 `binance`

    用这个值对象替代裸字符串后，调用方就不需要再约定 `ws.binance`
    这种隐式格式，代码语义会清晰很多。
    """

    # 组件类别。
    kind: ComponentKind
    # 类别下的具体名称。
    name: str

    @classmethod
    def exchange(cls, name: str) -> ComponentKey:
        """构造一个交易所组件标识。"""

        return cls(ComponentKind.EXCHANGE, name)

    @classmethod
    def websocket(cls, name: str) -> ComponentKey:
        """构造一个 websocket 组件标识。"""

        return cls(ComponentKind.WS, name)

    @property
    def label(self) -> str:
        """返回便于日志和展示的字符串形式。"""

        return f"{self.kind.value}.{self.name}"


@dataclass(slots=True, frozen=True)
class ComponentHeartbeat:
    """单个组件最近一次心跳记录。

    这个模型只保存最小必要信息：
    - `component`：是哪一个组件
    - `last_heartbeat_at`：最近一次成功上报心跳的时间
    """

    # 当前记录对应的组件标识。
    component: ComponentKey
    # 最近一次被观察到“还活着”的时间。
    last_heartbeat_at: datetime


class HealthChecker:
    """跟踪组件存活状态的轻量检查器。

    使用方式很简单：
    1. 组件每次成功完成关键动作后调用 `heartbeat()`
    2. 检查器记录该组件最近一次活跃时间
    3. 调用 `unhealthy_components()` 或 `is_healthy()` 判断是否超时失活

    这里的“健康”定义是基于时间窗口的：
    - 如果组件最近一次心跳距离现在没有超过 `max_staleness`，视为健康
    - 如果超过这个阈值，则视为不健康
    """

    def __init__(self, *, max_staleness: timedelta = timedelta(seconds=60)) -> None:
        """初始化健康检查器。

        参数：
        - `max_staleness`：允许组件最长多久不报心跳；超过该时长即视为 stale
        """

        # 超过该时长没有心跳，就认为组件已经不健康。
        self.max_staleness = max_staleness
        # 按组件键保存最近一次心跳记录。
        self._components: dict[ComponentKey, ComponentHeartbeat] = {}

    def heartbeat(self, component: ComponentKey, *, at: datetime | None = None) -> None:
        """记录某个组件的一次心跳。

        一般在组件成功完成一次关键工作后调用，例如：
        - 成功抓到一次交易所快照
        - 成功收到一条 websocket 消息

        如果同一个组件重复上报心跳，会直接覆盖旧的时间戳，
        因为我们只关心“最近一次”活跃时间。
        """

        # 未显式传入时间时，默认记录当前 UTC 时间。
        self._components[component] = ComponentHeartbeat(component, at or utc_now())

    def unhealthy_components(self, *, now: datetime | None = None) -> list[ComponentKey]:
        """返回当前所有已经失活的组件标识。

        判定标准：
        - 取当前时间 `now`
        - 计算 `current - component.last_heartbeat_at`
        - 如果该间隔大于 `max_staleness`，就把该组件记为不健康

        返回值保留 `ComponentKey`，而不是压扁成一个裸字符串，
        这样调用方仍然能知道它到底是哪一类组件。
        """

        # 允许测试或调用方显式传入当前时间，便于可重复验证。
        current = now or utc_now()
        return [
            heartbeat.component
            # 只要距离最近一次心跳的时间超过阈值，就认为组件 stale。
            for heartbeat in self._components.values()
            if current - heartbeat.last_heartbeat_at > self.max_staleness
        ]

    def is_healthy(self, *, now: datetime | None = None) -> bool:
        """判断当前是否所有已登记组件都仍然健康。

        这是一个整体级别的便捷接口：
        - 只要存在任意一个 stale 组件，就返回 `False`
        - 只有所有组件都没超时，才返回 `True`
        """

        return not self.unhealthy_components(now=now)
