from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arb.integrations.feishu.cards import build_action_card, build_positions_card, build_strategies_card
from arb.integrations.feishu.client import FeishuClient
from arb.integrations.feishu.events import FeishuEventHandler, sign_callback


class FeishuClientTests(unittest.TestCase):
    def test_token_refresh_and_message_send(self) -> None:
        calls: list[dict[str, object]] = []

        def transport(request):
            calls.append(request)
            if request["url"].endswith("/tenant_access_token/internal"):
                return {"tenant_access_token": "token-1", "expire": 7200}
            return {"data": {"message_id": "om_xxx"}}

        client = FeishuClient("app", "secret", transport)
        token = client.get_tenant_access_token(now=0)
        response = client.send_card(receive_id="ou_xxx", card={"hello": "world"})
        self.assertEqual(token, "token-1")
        self.assertEqual(response["data"]["message_id"], "om_xxx")
        self.assertEqual(len(calls), 2)

    def test_request_retries_once(self) -> None:
        state = {"count": 0}

        def transport(request):
            state["count"] += 1
            if state["count"] == 1:
                raise RuntimeError("temporary failure")
            return {"tenant_access_token": "token-2", "expire": 7200}

        client = FeishuClient("app", "secret", transport)
        self.assertEqual(client.refresh_token(now=0), "token-2")
        self.assertEqual(state["count"], 2)


class FeishuEventsTests(unittest.TestCase):
    def test_callback_signature_and_challenge(self) -> None:
        handler = FeishuEventHandler(verification_token="verify", signing_secret="secret")
        raw_body = '{"type":"url_verification","challenge":"abc","token":"verify"}'
        headers = {
            "X-Lark-Request-Timestamp": "1700000000",
            "X-Lark-Request-Nonce": "nonce",
            "X-Lark-Signature": sign_callback("secret", "1700000000", "nonce", raw_body),
        }
        response = handler.parse_callback(headers, {"type": "url_verification", "challenge": "abc", "token": "verify"}, raw_body=raw_body)
        self.assertEqual(response["challenge"], "abc")

    def test_card_callback_is_parsed(self) -> None:
        handler = FeishuEventHandler(verification_token="verify")
        payload = {
            "token": "verify",
            "action": {"value": {"action": "close", "target": "spot_perp:BTC/USDT"}},
            "operator": {"open_id": "ou_xxx"},
        }
        response = handler.parse_callback({}, payload, raw_body="{}")
        self.assertEqual(response["type"], "card_action")
        self.assertEqual(response["action"]["action"], "close")


class FeishuCardsTests(unittest.TestCase):
    def test_cards_render_positions_and_actions(self) -> None:
        positions = build_positions_card(
            [{"exchange": "binance", "symbol": "BTC/USDT", "direction": "long", "quantity": "1"}]
        )
        strategies = build_strategies_card([{"name": "spot_perp", "status": "running"}])
        action = build_action_card("spot_perp:BTC/USDT", "close")
        self.assertIn("BTC/USDT", positions["elements"][0]["content"])
        self.assertIn("spot_perp", strategies["elements"][0]["content"])
        self.assertEqual(action["elements"][1]["actions"][0]["value"]["action"], "close")


if __name__ == "__main__":
    unittest.main()
