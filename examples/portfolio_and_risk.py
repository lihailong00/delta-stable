"""离线示例：仓位、余额、资金分配和风险检查。

运行：
PYTHONPATH=src uv run python examples/portfolio_and_risk.py
"""

from __future__ import annotations

from decimal import Decimal

from arb.models import MarketType, Position, PositionDirection
from arb.portfolio.allocator import CapitalAllocator
from arb.portfolio.balances import BalanceBook
from arb.portfolio.positions import PositionBook
from arb.risk.checks import RiskChecker


def main() -> None:
    balances = BalanceBook()
    balances.set_balance("binance", "USDT", Decimal("12000"))
    balances.reserve("binance", "USDT", Decimal("2500"))
    print("available margin", balances.available_margin("binance", "USDT"))

    positions = PositionBook()
    positions.add(
        Position(
            exchange="binance",
            symbol="BTC/USDT",
            market_type=MarketType.SPOT,
            direction=PositionDirection.LONG,
            quantity=Decimal("1"),
            entry_price=Decimal("100"),
            mark_price=Decimal("101"),
        )
    )
    positions.add(
        Position(
            exchange="okx",
            symbol="BTC/USDT",
            market_type=MarketType.PERPETUAL,
            direction=PositionDirection.SHORT,
            quantity=Decimal("0.96"),
            entry_price=Decimal("100"),
            mark_price=Decimal("100.5"),
        )
    )
    print("net exposure", positions.net_exposure_by_symbol())
    print("hedge ratio", positions.hedge_ratio("BTC/USDT"))
    print("is balanced", positions.is_balanced("BTC/USDT"))

    allocator = CapitalAllocator(
        max_per_symbol=Decimal("20000"),
        max_per_exchange=Decimal("15000"),
        max_total=Decimal("40000"),
    )
    decision = allocator.allocate(
        exchange="binance",
        symbol="BTC/USDT",
        requested_notional=Decimal("18000"),
        current_symbol_notional=Decimal("5000"),
        current_exchange_notional=Decimal("3000"),
        current_total_notional=Decimal("10000"),
    )
    print("allocation", decision)

    risk = RiskChecker()
    print(
        "naked leg alert",
        risk.check_naked_leg(
            symbol="BTC/USDT",
            long_quantity=Decimal("1"),
            short_quantity=Decimal("0.96"),
        ),
    )
    print(
        "basis alert",
        risk.check_basis(
            symbol="BTC/USDT",
            spot_price=Decimal("100"),
            perp_price=Decimal("101"),
            max_basis_bps=Decimal("20"),
        ),
    )


if __name__ == "__main__":
    main()
