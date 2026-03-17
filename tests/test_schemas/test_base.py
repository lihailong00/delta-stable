from __future__ import annotations

import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.schemas.base import ArbFrozenModel, ArbModel


class MutableExample(ArbModel):
    amount: Decimal


class FrozenExample(ArbFrozenModel):
    created_at: datetime


class TestSchemaBase:
    def test_mutable_schema_validates_assignment(self) -> None:
        payload = MutableExample(amount=Decimal("1.5"))
        payload.amount = Decimal("2.0")
        assert payload.to_dict()["amount"] == Decimal("2.0")

    def test_frozen_schema_rejects_extra_and_mutation(self) -> None:
        payload = FrozenExample(created_at=datetime(2026, 3, 17, tzinfo=timezone.utc))
        with pytest.raises(ValueError):
            FrozenExample(created_at=payload.created_at, unexpected="x")
        with pytest.raises(Exception):
            payload.created_at = datetime(2026, 3, 18, tzinfo=timezone.utc)  # type: ignore[misc]

    def test_mapping_like_helpers_expose_fields(self) -> None:
        payload = MutableExample(amount=Decimal("3.0"))
        assert payload["amount"] == Decimal("3.0")
        assert payload.get("missing") is None
        assert list(payload.keys()) == ["amount"]
