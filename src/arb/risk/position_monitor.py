"""Ongoing position risk monitoring for funding arbitrage service."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from arb.funding import DEFAULT_FUNDING_INTERVAL_HOURS
from arb.scanner.cost_model import normalize_rate
from arb.risk.checks import RiskAlert, RiskChecker


@dataclass(slots=True)
class PositionMonitorDecision:
    alerts: list[RiskAlert] = field(default_factory=list)
    close_reason: str | None = None

    @property
    def should_close(self) -> bool:
        return self.close_reason is not None


class PositionMonitor:
    """Evaluate live funding arbitrage positions for close / reduce-only decisions."""

    def __init__(
        self,
        *,
        risk_checker: RiskChecker | None = None,
        max_basis_bps: Decimal = Decimal("25"),
        min_buffer_bps: Decimal = Decimal("30"),
        naked_tolerance: Decimal = Decimal("0.02"),
    ) -> None:
        self.risk_checker = risk_checker or RiskChecker()
        self.max_basis_bps = max_basis_bps
        self.min_buffer_bps = min_buffer_bps
        self.naked_tolerance = naked_tolerance

    def evaluate(
        self,
        *,
        symbol: str,
        snapshot: dict[str, Any],
        spot_quantity: Decimal,
        perp_quantity: Decimal,
        opened_at: datetime | None,
        max_holding_period: timedelta,
        min_expected_rate: Decimal,
        funding_interval_hours: int = DEFAULT_FUNDING_INTERVAL_HOURS,
        comparison_interval_hours: int = DEFAULT_FUNDING_INTERVAL_HOURS,
        liquidation_price: Decimal | None = None,
        now: datetime | None = None,
    ) -> PositionMonitorDecision:
        alerts: list[RiskAlert] = []
        funding = snapshot.get("funding", {})
        funding_alert = self.risk_checker.check_funding_reversal(
            symbol=symbol,
            current_rate=normalize_rate(
                Decimal(str(funding.get("rate", "0"))),
                from_interval_hours=funding_interval_hours,
                to_interval_hours=comparison_interval_hours,
            ),
            min_expected_rate=min_expected_rate,
        )
        if funding_alert is not None:
            alerts.append(funding_alert)

        holding_alert = self.risk_checker.check_holding_period(
            symbol=symbol,
            opened_at=opened_at,
            max_holding_period=max_holding_period,
            now=now,
        )
        if holding_alert is not None:
            alerts.append(holding_alert)

        naked_alert = self.risk_checker.check_naked_leg(
            symbol=symbol,
            long_quantity=spot_quantity,
            short_quantity=perp_quantity,
            tolerance=self.naked_tolerance,
        )
        if naked_alert is not None:
            alerts.append(naked_alert)

        view = snapshot.get("view")
        if isinstance(view, dict):
            basis_alert = self.risk_checker.check_basis(
                symbol=symbol,
                spot_price=Decimal(str(view["spot_ticker"]["ask"])),
                perp_price=Decimal(str(view["perp_ticker"]["bid"])),
                max_basis_bps=self.max_basis_bps,
            )
            if basis_alert is not None:
                alerts.append(basis_alert)

        if liquidation_price is not None:
            ticker = snapshot.get("ticker", {})
            mark_price = Decimal(str(ticker.get("last", ticker.get("bid", "0"))))
            liquidation_alert = self.risk_checker.check_liquidation_buffer(
                symbol=symbol,
                mark_price=mark_price,
                liquidation_price=liquidation_price,
                min_buffer_bps=self.min_buffer_bps,
            )
            if liquidation_alert is not None:
                alerts.append(liquidation_alert)

        close_reason = self.risk_checker.choose_close_reason(alerts, default="manual_close") if alerts else None
        return PositionMonitorDecision(alerts=alerts, close_reason=close_reason)
