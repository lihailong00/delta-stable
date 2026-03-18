"""Funding opportunity scanner."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal

from arb.funding import DEFAULT_FUNDING_INTERVAL_HOURS
from arb.market.schemas import MarketSnapshot, coerce_market_snapshot
from arb.schemas.base import ArbFrozenModel, SerializableValue

from arb.scanner.cost_model import annualize_rate, daily_rate, estimate_net_rate, hourly_rate
from arb.scanner.filters import filter_opportunities


class FundingOpportunity(ArbFrozenModel):
    exchange: str
    symbol: str
    gross_rate: Decimal
    net_rate: Decimal
    funding_interval_hours: int = DEFAULT_FUNDING_INTERVAL_HOURS
    hourly_net_rate: Decimal = Decimal("0")
    daily_net_rate: Decimal = Decimal("0")
    annualized_net_rate: Decimal
    spread_bps: Decimal
    liquidity_usd: Decimal


class FundingScanner:
    """Scan standardized snapshots for positive net funding opportunities."""

    def __init__(
        self,
        *,
        trading_fee_rate: Decimal = Decimal("0"),
        slippage_rate: Decimal = Decimal("0"),
        borrow_rate: Decimal = Decimal("0"),
        transfer_rate: Decimal = Decimal("0"),
        min_net_rate: Decimal = Decimal("0"),
        min_liquidity_usd: Decimal = Decimal("0"),
        whitelist: set[str] | None = None,
        blacklist: set[str] | None = None,
    ) -> None:
        self.trading_fee_rate = trading_fee_rate
        self.slippage_rate = slippage_rate
        self.borrow_rate = borrow_rate
        self.transfer_rate = transfer_rate
        self.min_net_rate = min_net_rate
        self.min_liquidity_usd = min_liquidity_usd
        self.whitelist = whitelist
        self.blacklist = blacklist

    def scan(
        self,
        snapshots: Sequence[MarketSnapshot | Mapping[str, SerializableValue]],
    ) -> list[FundingOpportunity]:
        candidates: list[FundingOpportunity] = []
        for raw_snapshot in snapshots:
            snapshot = self._coerce_snapshot(raw_snapshot)
            funding = snapshot.funding
            ticker = snapshot.ticker
            if not funding or not ticker:
                continue
            gross_rate = funding.rate
            interval_hours = funding.funding_interval_hours
            net_rate = estimate_net_rate(
                gross_rate,
                trading_fee_rate=self.trading_fee_rate,
                slippage_rate=self.slippage_rate,
                borrow_rate=self.borrow_rate,
                transfer_rate=self.transfer_rate,
            )
            bid = ticker.bid
            ask = ticker.ask
            mid = (bid + ask) / Decimal("2")
            spread_bps = ((ask - bid) / mid) * Decimal("10000") if mid else Decimal("0")
            liquidity_usd = snapshot.liquidity_usd
            if liquidity_usd is None:
                liquidity_usd = ask * (snapshot.top_ask_size or Decimal("0"))
            opportunity = FundingOpportunity(
                exchange=funding.exchange,
                symbol=funding.symbol,
                gross_rate=gross_rate,
                net_rate=net_rate,
                funding_interval_hours=interval_hours,
                hourly_net_rate=hourly_rate(net_rate, interval_hours=interval_hours),
                daily_net_rate=daily_rate(net_rate, interval_hours=interval_hours),
                annualized_net_rate=annualize_rate(net_rate, interval_hours=interval_hours),
                spread_bps=spread_bps,
                liquidity_usd=liquidity_usd,
            )
            candidates.append(opportunity)

        filtered = filter_opportunities(
            candidates,
            min_net_rate=self.min_net_rate,
            min_liquidity_usd=self.min_liquidity_usd,
            whitelist=self.whitelist,
            blacklist=self.blacklist,
        )
        return sorted(filtered, key=lambda item: item.annualized_net_rate, reverse=True)

    @staticmethod
    def _coerce_snapshot(
        snapshot: MarketSnapshot | Mapping[str, SerializableValue],
    ) -> MarketSnapshot:
        if isinstance(snapshot, MarketSnapshot):
            return snapshot
        return coerce_market_snapshot(dict(snapshot))
