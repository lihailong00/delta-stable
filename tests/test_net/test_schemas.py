from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.net.schemas import HttpRequest, coerce_http_request


class TestNetSchemas:
    def test_compat_http_request_keeps_exchange_fields(self) -> None:
        request = HttpRequest(
            method="GET",
            url="https://example.com/api/ping",
            signed=True,
            market_type="perpetual",
        )

        assert request.signed is True
        assert request.market_type == "perpetual"

    def test_compat_coerce_http_request_accepts_legacy_mapping(self) -> None:
        request = coerce_http_request(
            {
                "method": "POST",
                "url": "https://example.com/api/order",
                "body": {"symbol": "BTCUSDT"},
                "signed": True,
                "market_type": "spot",
            }
        )

        assert request.json_body == {"symbol": "BTCUSDT"}
        assert request.signed is True
        assert request.market_type == "spot"
