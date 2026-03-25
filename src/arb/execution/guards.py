"""下单前校验守卫。

这个模块负责在真正调用交易所下单接口之前，先做一层本地快速校验，
避免明显不合法或超出约束的订单直接进入执行链路。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


class GuardViolation(Exception):
    """下单前校验失败时抛出的异常。"""


@dataclass(slots=True, frozen=True)
class GuardContext:
    """单条交易腿做本地校验所需的上下文。"""

    # 当前可用于本次下单的可用余额。
    available_balance: Decimal
    # 允许的最大名义价值上限。
    max_notional: Decimal
    # 当前账户/市场允许交易的标的集合。
    supported_symbols: set[str]


class PreTradeGuards:
    """执行前守卫。

    这个类只负责做“本地快速拒绝”，不和交易所通信，也不负责风控告警落库。
    它的目标是尽早挡住明显有问题的下单请求，例如：
    - 交易对不受支持
    - 下单名义价值超过本地配置上限
    - 名义价值超过当前可用余额
    """

    def validate(
        self,
        *,
        symbol: str,
        quantity: Decimal,
        price: Decimal,
        context: GuardContext,
    ) -> None:
        """校验单条交易腿是否满足最基本的下单条件。

        校验顺序：
        1. 先检查交易标的是否受支持
        2. 再计算名义价值 `quantity * price`
        3. 检查是否超过配置上限
        4. 检查是否超过可用余额

        任意一步失败都会直接抛出 `GuardViolation`，由上层决定如何中止执行。
        """

        # 先做最基础的标的合法性检查，不支持的交易对不应继续往下走。
        if symbol not in context.supported_symbols:
            raise GuardViolation(f"unsupported symbol: {symbol}")
        # 名义价值用于统一衡量这笔订单的规模。
        notional = quantity * price
        # 先检查是否突破本地配置的风险上限。
        if notional > context.max_notional:
            raise GuardViolation("notional exceeds configured limit")
        # 再检查当前账户视角下是否有足够余额承接这笔订单。
        if notional > context.available_balance:
            raise GuardViolation("insufficient balance")
