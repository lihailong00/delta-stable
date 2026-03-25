"""执行路由辅助工具。

这个模块负责回答执行层的几个基础问题：
- 当前订单应该走 maker 还是 taker
- 应该优先发到哪个交易所
- 在给定参考价的前提下，最终挂单价格应该是多少
- 什么时候需要从 maker 升级到更激进的 taker 执行
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from arb.models import Side


class RouteMode(StrEnum):
    """执行模式枚举。"""

    # 以更优价格挂单，追求手续费/成交价优势，但不保证立即成交。
    MAKER = "maker"
    # 以更积极价格直接吃单，优先保证成交速度。
    TAKER = "taker"


@dataclass(slots=True, frozen=True)
class RouteDecision:
    """一次路由决策的最终输出。"""

    # 最终选择的执行模式。
    mode: RouteMode
    # 最终选择的交易所。
    exchange: str
    # 这次路由是否处于紧急模式。
    urgent: bool = False


class ExecutionRouter:
    """执行路由器。

    这个类本身不负责下单，它只负责根据紧急程度、手续费、价差和可用性，
    为上层 workflow 提供一个稳定、统一的路由结果。
    """

    def choose_mode(
        self,
        *,
        urgent: bool,
        maker_fee_rate: Decimal,
        taker_fee_rate: Decimal,
        spread_bps: Decimal,
    ) -> RouteMode:
        """决定本次执行使用 maker 还是 taker。

        当前规则非常直接：
        - 只要是紧急模式，优先 taker
        - 只要价差太小（<= 1 bps），也直接走 taker
        - 否则比较 maker/taker 手续费，成本更低的一侧优先
        """

        # 紧急模式下优先保证成交速度；极小价差下走 maker 的收益通常也不明显。
        if urgent or spread_bps <= Decimal("1"):
            return RouteMode.TAKER
        # 非紧急时优先选择成本更低的模式。
        return RouteMode.MAKER if maker_fee_rate <= taker_fee_rate else RouteMode.TAKER

    def choose_exchange(
        self,
        *,
        preferred_exchange: str,
        fallback_exchange: str | None = None,
        exchange_available: bool = True,
    ) -> str:
        """在首选交易所和备选交易所之间做选择。"""

        # 首选交易所可用，或者根本没有备选时，直接用首选。
        if exchange_available or fallback_exchange is None:
            return preferred_exchange
        # 首选不可用时，回退到备选交易所。
        return fallback_exchange

    def route(
        self,
        *,
        preferred_exchange: str,
        urgent: bool,
        maker_fee_rate: Decimal,
        taker_fee_rate: Decimal,
        spread_bps: Decimal,
        fallback_exchange: str | None = None,
        exchange_available: bool = True,
    ) -> RouteDecision:
        """组合执行模式和交易所选择，生成完整路由决策。"""

        return RouteDecision(
            # 先决定是走 maker 还是 taker。
            mode=self.choose_mode(
                urgent=urgent,
                maker_fee_rate=maker_fee_rate,
                taker_fee_rate=taker_fee_rate,
                spread_bps=spread_bps,
            ),
            # 再决定本次应该由哪个交易所承接执行。
            exchange=self.choose_exchange(
                preferred_exchange=preferred_exchange,
                fallback_exchange=fallback_exchange,
                exchange_available=exchange_available,
            ),
            urgent=urgent,
        )

    def quote_price(
        self,
        *,
        reference_price: Decimal,
        side: str | Side,
        mode: RouteMode | str,
        max_slippage_bps: Decimal = Decimal("0"),
    ) -> Decimal:
        """根据执行模式和方向，生成最终报价。

        规则如下：
        - maker 模式下直接返回参考价，不主动让价
        - taker 模式下按 `max_slippage_bps` 做一个最坏情况让价
          - 买单提高价格，提升成交概率
          - 卖单压低价格，提升成交概率
        """

        # maker 模式或未配置滑点时，不对参考价做调整。
        if mode == RouteMode.MAKER or max_slippage_bps <= 0:
            return reference_price
        # 把 bps 转换为价格乘数。
        multiplier = Decimal("1") + (max_slippage_bps / Decimal("10000"))
        # side 允许传入字符串，因此先统一归一化成枚举。
        normalized_side = Side(str(side).lower())
        if normalized_side is Side.BUY:
            # 买单向上加价，避免因为报价太保守而挂不出去。
            return reference_price * multiplier
        # 卖单向下让价，以更容易成交。
        return reference_price / multiplier

    def should_escalate_to_taker(
        self,
        *,
        current_mode: RouteMode | str,
        elapsed_seconds: float,
        max_naked_seconds: float,
    ) -> bool:
        """判断当前执行是否应该升级为 taker。

        这是 workflow 在重试或处理裸腿风险时会用到的辅助判断：
        - 当前不是 taker
        - 配置了有效的裸腿时间阈值
        - 实际等待时间已经超过阈值

        只有同时满足这些条件，才认为应该升级为更激进的 taker。
        """

        return (
            current_mode != RouteMode.TAKER
            and max_naked_seconds > 0
            and elapsed_seconds >= max_naked_seconds
        )
