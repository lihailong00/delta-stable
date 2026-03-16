from __future__ import annotations
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from arb.strategy.engine import StrategyAction, StrategyDecision, StrategyEngine, StrategyState
from arb.strategy.perp_spread import PerpSpreadInputs, PerpSpreadStrategy
from arb.strategy.spot_perp import SpotPerpInputs, SpotPerpStrategy

class TestSpotPerpStrategy:

    def test_open_conditions_trigger_for_positive_funding(self) -> None:
        strategy = SpotPerpStrategy(min_open_funding_rate=Decimal('0.0005'))
        decision = strategy.evaluate(SpotPerpInputs(symbol='BTC/USDT', funding_rate=Decimal('0.0008'), spot_price=Decimal('100'), perp_price=Decimal('100.1')))
        assert decision.action == StrategyAction.OPEN

    def test_hedge_ratio_and_rebalance_trigger(self) -> None:
        strategy = SpotPerpStrategy(rebalance_threshold=Decimal('0.02'))
        state = StrategyState(is_open=True, opened_at=datetime.now(tz=timezone.utc), hedge_ratio=Decimal('1'))
        decision = strategy.evaluate(SpotPerpInputs(symbol='BTC/USDT', funding_rate=Decimal('0.001'), spot_price=Decimal('100'), perp_price=Decimal('100'), spot_quantity=Decimal('1'), perp_quantity=Decimal('0.95')), state=state)
        assert strategy.target_hedge_ratio(spot_quantity=Decimal('1'), perp_quantity=Decimal('0.95')) == Decimal('0.95')
        assert decision.action == StrategyAction.REBALANCE

    def test_close_when_holding_period_exceeded(self) -> None:
        strategy = SpotPerpStrategy(max_holding_period=timedelta(hours=1))
        state = StrategyState(is_open=True, opened_at=datetime.now(tz=timezone.utc) - timedelta(hours=2), hedge_ratio=Decimal('1'))
        decision = strategy.evaluate(SpotPerpInputs(symbol='BTC/USDT', funding_rate=Decimal('0.001'), spot_price=Decimal('100'), perp_price=Decimal('100')), state=state)
        assert decision.action == StrategyAction.CLOSE

class TestPerpSpreadStrategy:

    def test_cross_exchange_open_and_rebalance(self) -> None:
        strategy = PerpSpreadStrategy(min_spread_rate=Decimal('0.0004'), rebalance_threshold=Decimal('0.02'))
        open_decision = strategy.evaluate(PerpSpreadInputs(symbol='ETH/USDT', long_exchange='okx', short_exchange='binance', long_funding_rate=Decimal('0.0001'), short_funding_rate=Decimal('0.0008'), long_price=Decimal('100'), short_price=Decimal('100')))
        assert open_decision.action == StrategyAction.OPEN
        rebalance = strategy.evaluate(PerpSpreadInputs(symbol='ETH/USDT', long_exchange='okx', short_exchange='binance', long_funding_rate=Decimal('0.0001'), short_funding_rate=Decimal('0.0008'), long_price=Decimal('100'), short_price=Decimal('100'), long_quantity=Decimal('1'), short_quantity=Decimal('0.95')), state=StrategyState(is_open=True, hedge_ratio=Decimal('1')))
        assert rebalance.action == StrategyAction.REBALANCE

class TestStrategyEngine:

    def test_state_machine_applies_open_rebalance_close(self) -> None:
        engine = StrategyEngine()
        state = StrategyState()
        engine.transition(state, StrategyDecision(StrategyAction.OPEN, 'open', target_hedge_ratio=Decimal('1')))
        assert state.is_open
        engine.transition(state, StrategyDecision(StrategyAction.REBALANCE, 'rebalance', target_hedge_ratio=Decimal('0.98')))
        assert state.hedge_ratio == Decimal('0.98')
        engine.transition(state, StrategyDecision(StrategyAction.CLOSE, 'close'))
        assert not state.is_open
