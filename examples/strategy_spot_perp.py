"""离线示例：策略状态机和 spot/perp 决策。

运行：
PYTHONPATH=src uv run python examples/strategy_spot_perp.py
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from arb.strategy.engine import StrategyEngine, StrategyState
from arb.strategy.spot_perp import SpotPerpInputs, SpotPerpStrategy


def main() -> None:
    strategy = SpotPerpStrategy(
        min_open_funding_rate=Decimal("0.0005"),
        close_funding_rate=Decimal("0.0001"),
        max_holding_period=timedelta(days=3),
    )
    engine = StrategyEngine()
    state = StrategyState()

    open_decision = strategy.evaluate(
        SpotPerpInputs(
            symbol="BTC/USDT",
            funding_rate=Decimal("0.0008"),
            spot_price=Decimal("100"),
            perp_price=Decimal("100.1"),
        ),
        state=state,
    )
    engine.transition(state, open_decision)
    print("after open", open_decision, state)

    rebalance_decision = strategy.evaluate(
        SpotPerpInputs(
            symbol="BTC/USDT",
            funding_rate=Decimal("0.0007"),
            spot_price=Decimal("100"),
            perp_price=Decimal("100.05"),
            spot_quantity=Decimal("1.0"),
            perp_quantity=Decimal("0.85"),
        ),
        state=state,
    )
    engine.transition(state, rebalance_decision)
    print("after rebalance", rebalance_decision, state)

    close_decision = strategy.evaluate(
        SpotPerpInputs(
            symbol="BTC/USDT",
            funding_rate=Decimal("0.00005"),
            spot_price=Decimal("100"),
            perp_price=Decimal("100.0"),
            spot_quantity=Decimal("1.0"),
            perp_quantity=Decimal("1.0"),
        ),
        state=state,
    )
    engine.transition(state, close_decision)
    print("after close", close_decision, state)


if __name__ == "__main__":
    main()
