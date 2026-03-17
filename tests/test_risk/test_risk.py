from __future__ import annotations
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from arb.risk.checks import RiskAlert, RiskChecker
from arb.risk.killswitch import KillSwitch
from arb.risk.limits import RiskLimits

class TestRiskChecker:

    def test_risk_thresholds_trigger_alerts(self) -> None:
        checker = RiskChecker()
        assert checker.check_liquidation_buffer(symbol='BTC/USDT', mark_price=Decimal('100'), liquidation_price=Decimal('99.8'), min_buffer_bps=Decimal('30')) is not None
        assert checker.check_basis(symbol='BTC/USDT', spot_price=Decimal('100'), perp_price=Decimal('101'), max_basis_bps=Decimal('50')) is not None
        assert checker.check_funding_reversal(symbol='BTC/USDT', current_rate=Decimal('-0.0001'), min_expected_rate=Decimal('0')) is not None
        assert checker.check_naked_leg(symbol='BTC/USDT', long_quantity=Decimal('1'), short_quantity=Decimal('0.9'), tolerance=Decimal('0.05')) is not None
        assert checker.check_holding_period(symbol='BTC/USDT', opened_at=datetime.now(tz=timezone.utc) - timedelta(hours=2), max_holding_period=timedelta(hours=1)) is not None

    def test_close_reason_priority_prefers_more_urgent_alert(self) -> None:
        checker = RiskChecker()
        reason = checker.choose_close_reason([
            RiskAlert('medium', 'holding_period_exceeded', 'BTC/USDT'),
            RiskAlert('medium', 'funding_reversal', 'BTC/USDT'),
        ])
        assert reason == 'funding_reversal'

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
        assert switch.requires_reduce_only()
        assert switch.close_reason() == 'manual'
        switch.trigger_stop('risk')
        assert switch.active
        assert switch.reduce_only
        assert switch.close_reason() == 'killswitch_active'
        switch.clear()
        assert not switch.active
        assert not switch.reduce_only
