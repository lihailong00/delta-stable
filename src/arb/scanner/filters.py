"""Opportunity filtering helpers."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from arb.scanner.funding_scanner import FundingOpportunity


def filter_opportunities(
    opportunities: Iterable["FundingOpportunity"],
    *,
    min_net_rate: Decimal = Decimal("0"),
    min_liquidity_usd: Decimal = Decimal("0"),
    whitelist: set[str] | None = None,
    blacklist: set[str] | None = None,
) -> list["FundingOpportunity"]:
    results: list["FundingOpportunity"] = []
    for opportunity in opportunities:
        if whitelist is not None and opportunity.symbol not in whitelist:
            continue
        if blacklist is not None and opportunity.symbol in blacklist:
            continue
        if opportunity.net_rate < min_net_rate:
            continue
        if opportunity.liquidity_usd < min_liquidity_usd:
            continue
        results.append(opportunity)
    return results
