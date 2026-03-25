"""Restart recovery helpers for in-flight workflows."""

from __future__ import annotations

from arb.models import MarketType
from arb.runtime.enums import WorkflowStatus
from arb.portfolio.reconciler import PortfolioReconciler
from arb.runtime.schemas import RecoveryPlan, WorkflowStateRecord
from arb.storage.repository import Repository


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
        client: object,
        *,
        exchange: str,
        market_type: MarketType = MarketType.PERPETUAL,
        symbol: str | None = None,
        workflow_statuses: tuple[WorkflowStatus, ...] = (
            WorkflowStatus.PENDING,
            WorkflowStatus.RUNNING,
            WorkflowStatus.CLOSING,
        ),
    ) -> RecoveryPlan:
        workflows = [
            WorkflowStateRecord.model_validate(workflow.to_dict() if hasattr(workflow, "to_dict") else workflow)
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
        exchange_positions = list(await client.fetch_positions(market_type, symbol=symbol))  # type: ignore[attr-defined]
        exchange_orders = list(await client.fetch_open_orders(symbol=symbol, market_type=market_type))  # type: ignore[attr-defined]
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
