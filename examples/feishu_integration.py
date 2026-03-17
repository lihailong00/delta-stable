"""离线示例：飞书 token、卡片发送和事件解析。

运行：
PYTHONPATH=src uv run python examples/feishu_integration.py
"""

from __future__ import annotations

import json

from arb.integrations.feishu.cards import build_action_card, build_positions_card, build_strategies_card
from arb.integrations.feishu.client import FeishuClient
from arb.integrations.feishu.events import FeishuEventHandler, sign_callback
from arb.integrations.feishu.schemas import FeishuTransportRequest
from arb.schemas.base import SerializableValue


def fake_transport(request: FeishuTransportRequest) -> dict[str, SerializableValue]:
    if "tenant_access_token" in request["url"]:
        return {"tenant_access_token": "tenant-token", "expire": 7200}
    return {
        "data": {
            "message_id": "om_xxx",
            "receive_id": request["json"]["receive_id"],
            "msg_type": request["json"]["msg_type"],
        }
    }


def main() -> None:
    client = FeishuClient("app-id", "app-secret", transport=fake_transport)
    positions_card = build_positions_card(
        [
            {"exchange": "binance", "symbol": "BTC/USDT", "direction": "long", "quantity": "1"},
            {"exchange": "okx", "symbol": "BTC/USDT", "direction": "short", "quantity": "1"},
        ]
    )
    strategies_card = build_strategies_card([{"name": "spot_perp", "status": "running"}])
    action_card = build_action_card("spot_perp:BTC/USDT", "close", confirm_text="确认平仓 BTC funding 仓位")

    print("positions card")
    print(json.dumps(positions_card.to_dict(), indent=2, ensure_ascii=False))
    print("strategies card")
    print(json.dumps(strategies_card.to_dict(), indent=2, ensure_ascii=False))
    print("send response", client.send_card(receive_id="ou_xxx", card=action_card))

    raw_body = json.dumps({"action": {"value": {"action": "close", "target": "spot_perp:BTC/USDT"}}})
    signature = sign_callback("signing-secret", "1700000000", "nonce-1", raw_body)
    handler = FeishuEventHandler(verification_token="verify-token", signing_secret="signing-secret")
    parsed = handler.parse_callback(
        {
            "X-Lark-Signature": signature,
            "X-Lark-Request-Timestamp": "1700000000",
            "X-Lark-Request-Nonce": "nonce-1",
        },
        {
            "token": "verify-token",
            "action": {"value": {"action": "close", "target": "spot_perp:BTC/USDT"}},
            "operator": {"open_id": "ou_xxx"},
        },
        raw_body=raw_body,
    )
    print("parsed callback", parsed.to_dict())


if __name__ == "__main__":
    main()
