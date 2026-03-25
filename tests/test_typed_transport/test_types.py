from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from typed_transport.types import HttpRequest


class TestTypedTransportTypes:
    def test_http_request_stays_generic(self) -> None:
        with pytest.raises(ValidationError):
            HttpRequest(
                method="GET",
                url="https://example.com/api/ping",
                signed=True,
            )

