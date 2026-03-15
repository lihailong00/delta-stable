"""PnL export helpers."""

from __future__ import annotations

import csv
import json
from io import StringIO
from typing import Any


def export_csv(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def export_json(rows: list[dict[str, Any]]) -> str:
    return json.dumps(rows, separators=(",", ":"), sort_keys=True)
