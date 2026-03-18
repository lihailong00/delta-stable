"""Ongoing position risk monitoring for funding arbitrage service."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from collections.abc import Mapping

from pydantic import Field

from arb.funding import DEFAULT_FUNDING_INTERVAL_HOURS
from arb.market.schemas import MarketSnapshot, coerce_funding_rate, coerce_ticker
from arb.market.spot_perp_view import SpotPerpQuoteView, build_spot_perp_view
from arb.models import MarketType
from arb.scanner.cost_model import normalize_rate
from arb.risk.checks import RiskAlert, RiskChecker
from arb.schemas.base import ArbFrozenModel, ArbModel, SerializableValue


class PositionMonitorSnapshot(ArbFrozenModel):
    ticker: object
    funding: object | None = None
    view: SpotPerpQuoteView | None = None

    @classmethod
    def from_snapshot(
        cls,
        snapshot: MarketSnapshot | Mapping[str, object],
        *,
        symbol: str,
    ) -> "PositionMonitorSnapshot":
        if isinstance(snapshot, MarketSnapshot):
            return cls(ticker=snapshot.ticker, funding=snapshot.funding)
        ticker_payload = snapshot.get("ticker")
        if not isinstance(ticker_payload, Mapping):
            raise TypeError("snapshot.ticker is required")
        funding_payload = snapshot.get("funding")
        view_payload = snapshot.get("view")
        view = None
        if isinstance(view_payload, Mapping) and isinstance(funding_payload, Mapping):
            spot_ticker = view_payload.get("spot_ticker")
            perp_ticker = view_payload.get("perp_ticker")
            if isinstance(spot_ticker, Mapping) and isinstance(perp_ticker, Mapping):
                exchange = str(funding_payload.get("exchange", ticker_payload.get("exchange", "")))
                view = build_spot_perp_view(
                    exchange=exchange,
                    symbol=symbol,
                    spot_ticker=dict(spot_ticker),
                    perp_ticker=dict(perp_ticker),
                    funding=dict(funding_payload),
                )
        return cls(
            ticker=coerce_ticker(
                dict(ticker_payload),
                default_symbol=symbol,
                default_market_type=MarketType.PERPETUAL,
            ),
            funding=(
                coerce_funding_rate(dict(funding_payload), default_symbol=symbol)
                if isinstance(funding_payload, Mapping)
                else None
            ),
            view=view,
        )


class PositionMonitorDecision(ArbModel):
    alerts: list[RiskAlert] = Field(default_factory=list)
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
        snapshot: PositionMonitorSnapshot | MarketSnapshot,
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
        normalized_snapshot = (
            snapshot
            if isinstance(snapshot, PositionMonitorSnapshot)
            else PositionMonitorSnapshot.from_snapshot(snapshot, symbol=symbol)
        )
        alerts: list[RiskAlert] = []
        funding = normalized_snapshot.funding
        funding_alert = self.risk_checker.check_funding_reversal(
            symbol=symbol,
            current_rate=normalize_rate(
                Decimal(str(getattr(funding, "rate", "0"))),
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

        view = normalized_snapshot.view
        if view is not None:
            basis_alert = self.risk_checker.check_basis(
                symbol=symbol,
                spot_price=view.spot_ticker.ask,
                perp_price=view.perp_ticker.bid,
                max_basis_bps=self.max_basis_bps,
            )
            if basis_alert is not None:
                alerts.append(basis_alert)

        if liquidation_price is not None:
            ticker = normalized_snapshot.ticker
            mark_price = Decimal(str(getattr(ticker, "last", getattr(ticker, "bid", "0"))))
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
