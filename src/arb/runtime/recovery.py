"""Restart recovery helpers for in-flight workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from arb.models import MarketType
from arb.portfolio.reconciler import PortfolioReconciler, ReconciliationReport
from arb.storage.repository import Repository


@dataclass(slots=True)
class RecoveryPlan:
    workflows: list[dict[str, Any]]
    reconciliation: ReconciliationReport
    exchange_positions: list[Any] = field(default_factory=list)
    exchange_orders: list[Any] = field(default_factory=list)


class WorkflowRecovery:
    """Load unfinished workflows and compare local state with exchange state."""

    def __init__(
        self,
        repository: Repository,
        *,
        reconciler: PortfolioReconciler | None = None,
    ) -> None:
        self.repository = repository
        self.reconciler = reconciler or PortfolioReconciler()

    async def recover(
        self,
        client: Any,
        *,
        exchange: str,
        market_type: MarketType = MarketType.PERPETUAL,
        symbol: str | None = None,
        workflow_statuses: tuple[str, ...] = ("pending", "running", "closing"),
    ) -> RecoveryPlan:
        workflows = [
            workflow
            for workflow in self.repository.list_workflow_states(statuses=workflow_statuses)
            if workflow["exchange"] == exchange and (symbol is None or workflow["symbol"] == symbol)
        ]
        local_positions = [
            position
            for position in self.repository.list_positions()
            if position["exchange"] == exchange
            and position["market_type"] == market_type.value
            and (symbol is None or position["symbol"] == symbol)
        ]
        local_orders = [
            order
            for order in self.repository.list_orders()
            if order["exchange"] == exchange
            and order["market_type"] == market_type.value
            and (symbol is None or order["symbol"] == symbol)
        ]
        exchange_positions = list(await client.fetch_positions(market_type, symbol=symbol))
        exchange_orders = list(await client.fetch_open_orders(symbol=symbol, market_type=market_type))
        reconciliation = self.reconciler.reconcile(
            local_positions=local_positions,
            exchange_positions=exchange_positions,
            local_orders=local_orders,
            exchange_orders=exchange_orders,
        )
        return RecoveryPlan(
            workflows=workflows,
            reconciliation=reconciliation,
            exchange_positions=exchange_positions,
            exchange_orders=exchange_orders,
        )
