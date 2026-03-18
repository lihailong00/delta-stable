"""Portfolio reconciliation helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal

from pydantic import Field

from arb.models import MarketType, Order, Position
from arb.schemas.base import ArbFrozenModel, ArbModel, SerializableValue
from arb.storage.schemas import StoredOrderRow, StoredPositionRow


class ReconciliationIssue(ArbFrozenModel):
    entity: str
    key: str
    issue: str


class ReconciliationReport(ArbModel):
    position_issues: list[ReconciliationIssue] = Field(default_factory=list)
    order_issues: list[ReconciliationIssue] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.position_issues and not self.order_issues


class PortfolioReconciler:
    """Compare local persistent state against exchange reality."""

    def reconcile(
        self,
        *,
        local_positions: Sequence[Position | StoredPositionRow | Mapping[str, SerializableValue]],
        exchange_positions: Sequence[Position],
        local_orders: Sequence[Order | StoredOrderRow | Mapping[str, SerializableValue]],
        exchange_orders: Sequence[Order],
        quantity_tolerance: Decimal = Decimal("0.000001"),
    ) -> ReconciliationReport:
        report = ReconciliationReport()
        report.position_issues.extend(
            self._reconcile_positions(local_positions, exchange_positions, quantity_tolerance)
        )
        report.order_issues.extend(self._reconcile_orders(local_orders, exchange_orders))
        return report

    def _reconcile_positions(
        self,
        local_positions: Sequence[Position | StoredPositionRow | Mapping[str, SerializableValue]],
        exchange_positions: Sequence[Position],
        quantity_tolerance: Decimal,
    ) -> list[ReconciliationIssue]:
        exchange_index = {self._position_key(position): position for position in exchange_positions}
        local_index = {self._position_key(position): position for position in local_positions}
        issues: list[ReconciliationIssue] = []

        for key, local in local_index.items():
            exchange_position = exchange_index.get(key)
            local_quantity = self._position_quantity(local)
            if exchange_position is None:
                issues.append(ReconciliationIssue(entity="position", key=key, issue="missing_exchange_position"))
                continue
            if abs(local_quantity - exchange_position.quantity) > quantity_tolerance:
                issues.append(ReconciliationIssue(entity="position", key=key, issue="position_quantity_mismatch"))

        for key in exchange_index:
            if key not in local_index:
                issues.append(ReconciliationIssue(entity="position", key=key, issue="missing_local_position"))
        return issues

    def _reconcile_orders(
        self,
        local_orders: Sequence[Order | StoredOrderRow | Mapping[str, SerializableValue]],
        exchange_orders: Sequence[Order],
    ) -> list[ReconciliationIssue]:
        exchange_index = {self._order_key(order): order for order in exchange_orders}
        local_index = {self._order_key(order): order for order in local_orders}
        issues: list[ReconciliationIssue] = []

        for key, local in local_index.items():
            exchange_order = exchange_index.get(key)
            local_status = self._order_status(local)
            if exchange_order is None and local_status in {"new", "partially_filled"}:
                issues.append(ReconciliationIssue(entity="order", key=key, issue="stale_local_open_order"))
                continue
            if exchange_order is not None and local_status != exchange_order.status.value:
                issues.append(ReconciliationIssue(entity="order", key=key, issue="order_status_mismatch"))

        for key in exchange_index:
            if key not in local_index:
                issues.append(ReconciliationIssue(entity="order", key=key, issue="missing_local_order"))
        return issues

    def _position_key(
        self,
        position: Position | StoredPositionRow | Mapping[str, SerializableValue],
    ) -> str:
        if isinstance(position, Position):
            parts = (
                position.exchange,
                position.symbol,
                position.market_type.value,
                position.direction.value,
            )
        elif isinstance(position, StoredPositionRow):
            parts = (
                position.exchange,
                position.symbol,
                position.market_type,
                position.direction,
            )
        else:
            parts = (
                str(position["exchange"]),
                str(position["symbol"]),
                str(position["market_type"]),
                str(position["direction"]),
            )
        return "|".join(parts)

    def _position_quantity(
        self,
        position: Position | StoredPositionRow | Mapping[str, SerializableValue],
    ) -> Decimal:
        if isinstance(position, Position):
            return position.quantity
        if isinstance(position, StoredPositionRow):
            return Decimal(position.quantity)
        return Decimal(str(position["quantity"]))

    def _order_key(self, order: Order | StoredOrderRow | Mapping[str, SerializableValue]) -> str:
        if isinstance(order, Order):
            return str(order.order_id)
        if isinstance(order, StoredOrderRow):
            return str(order.order_id)
        return str(order["order_id"])

    def _order_status(self, order: Order | StoredOrderRow | Mapping[str, SerializableValue]) -> str:
        if isinstance(order, Order):
            return order.status.value
        if isinstance(order, StoredOrderRow):
            return order.status
        return str(order["status"])
