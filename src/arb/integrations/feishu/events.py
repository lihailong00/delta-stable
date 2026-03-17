"""Feishu event verification and parsing."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from typing import Any


def sign_callback(secret: str, timestamp: str, nonce: str, body: str) -> str:
    payload = f"{timestamp}:{nonce}:{body}"
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


class FeishuEventHandler:
    """Verify Feishu callback metadata and parse event payloads."""

    def __init__(self, *, verification_token: str | None = None, signing_secret: str | None = None) -> None:
        self.verification_token = verification_token
        self.signing_secret = signing_secret

    def verify_signature(
        self,
        *,
        body: str,
        timestamp: str,
        nonce: str,
        signature: str,
    ) -> bool:
        if not self.signing_secret:
            return True
        expected = sign_callback(self.signing_secret, timestamp, nonce, body)
        return hmac.compare_digest(expected, signature)

    def parse_callback(self, headers: Mapping[str, str], payload: Mapping[str, Any], *, raw_body: str) -> dict[str, Any]:
        if self.verification_token and payload.get("token") not in {None, self.verification_token}:
            raise PermissionError("invalid verification token")

        signature = headers.get("X-Lark-Signature") or headers.get("x-lark-signature")
        timestamp = headers.get("X-Lark-Request-Timestamp") or headers.get("x-lark-request-timestamp")
        nonce = headers.get("X-Lark-Request-Nonce") or headers.get("x-lark-request-nonce")
        if self.signing_secret and (not signature or not timestamp or not nonce):
            raise PermissionError("missing signature headers")
        if signature and timestamp and nonce and not self.verify_signature(
            body=raw_body,
            timestamp=timestamp,
            nonce=nonce,
            signature=signature,
        ):
            raise PermissionError("invalid callback signature")

        if payload.get("type") == "url_verification":
            return {"challenge": payload["challenge"]}
        if "action" in payload:
            return {
                "type": "card_action",
                "action": payload["action"]["value"],
                "operator_id": payload.get("operator", {}).get("open_id"),
            }
        return {"type": "event", "event": payload.get("event", {})}

    def to_command_payload(self, callback: Mapping[str, Any]) -> dict[str, Any]:
        action = dict(callback.get("action", {}))
        command: dict[str, Any] = {
            "action": str(action.get("action", "")),
            "requested_by": str(callback.get("operator_id", "")),
        }
        if "target" in action:
            command["target"] = str(action["target"])
        if "command_id" in action:
            command["command_id"] = str(action["command_id"])
        if "require_confirmation" in action:
            command["require_confirmation"] = bool(action["require_confirmation"])
        return command
