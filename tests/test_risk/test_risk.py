from __future__ import annotations
import sys
from decimal import Decimal
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from arb.risk.checks import RiskChecker
from arb.risk.killswitch import KillSwitch
from arb.risk.limits import RiskLimits

class TestRiskChecker:

    def test_risk_thresholds_trigger_alerts(self) -> None:
        checker = RiskChecker()
        assert checker.check_liquidation_buffer(symbol='BTC/USDT', mark_price=Decimal('100'), liquidation_price=Decimal('99.8'), min_buffer_bps=Decimal('30')) is not None
        assert checker.check_basis(symbol='BTC/USDT', spot_price=Decimal('100'), perp_price=Decimal('101'), max_basis_bps=Decimal('50')) is not None
        assert checker.check_funding_reversal(symbol='BTC/USDT', current_rate=Decimal('-0.0001'), min_expected_rate=Decimal('0')) is not None
        assert checker.check_naked_leg(symbol='BTC/USDT', long_quantity=Decimal('1'), short_quantity=Decimal('0.9'), tolerance=Decimal('0.05')) is not None

class TestRiskLimits:

    def test_limits_validate_leverage_and_position_size(self) -> None:
        limits = RiskLimits(max_leverage=Decimal('3'), max_position_notional=Decimal('10000'))
        assert limits.validate_leverage(Decimal('2'))
        assert not limits.validate_leverage(Decimal('4'))
        assert limits.validate_position_size(Decimal('5000'))
        assert not limits.validate_position_size(Decimal('12000'))

class TestKillSwitch:

    def test_reduce_only_and_stop_modes(self) -> None:
        switch = KillSwitch()
        switch.enable_reduce_only('manual')
        assert switch.reduce_only
        assert not switch.active
        switch.trigger_stop('risk')
        assert switch.active
        assert switch.reduce_only
        switch.clear()
        assert not switch.active
        assert not switch.reduce_only
