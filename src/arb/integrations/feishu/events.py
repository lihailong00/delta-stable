"""Feishu event verification and parsing."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from typing import Protocol

from arb.control.schemas import CommandRequest
from arb.integrations.feishu.schemas import FeishuParsedCallback
from arb.schemas.base import SerializableValue


class ControlApiLike(Protocol):
    def submit_command(self, token: str, request: CommandRequest) -> dict[str, SerializableValue]: ...

    def confirm_command(self, token: str, command_id: str, actor: str) -> dict[str, SerializableValue]: ...

    def cancel_command(self, token: str, command_id: str, actor: str) -> dict[str, SerializableValue]: ...


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

    def parse_callback(
        self,
        headers: Mapping[str, str],
        payload: Mapping[str, SerializableValue],
        *,
        raw_body: str,
    ) -> FeishuParsedCallback:
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
            return FeishuParsedCallback(type="url_verification", challenge=str(payload["challenge"]))
        if "action" in payload:
            action = payload["action"]
            if not isinstance(action, Mapping):
                raise ValueError("invalid action payload")
            operator = payload.get("operator")
            operator_id = None
            if isinstance(operator, Mapping):
                open_id = operator.get("open_id")
                operator_id = None if open_id is None else str(open_id)
            return FeishuParsedCallback(
                type="card_action",
                action=dict(action.get("value", {})) if isinstance(action.get("value", {}), Mapping) else {},
                operator_id=operator_id,
            )
        event = payload.get("event")
        return FeishuParsedCallback(
            type="event",
            event=dict(event) if isinstance(event, Mapping) else {},
        )

    def to_command_payload(self, callback: FeishuParsedCallback | Mapping[str, SerializableValue]) -> CommandRequest:
        parsed = callback if isinstance(callback, FeishuParsedCallback) else FeishuParsedCallback.model_validate(callback)
        action = dict(parsed.action)
        return CommandRequest(
            action=str(action.get("action", "")),
            target=str(action.get("target", "")),
            requested_by=str(parsed.operator_id or ""),
            require_confirmation=bool(action.get("require_confirmation", False)),
            payload=dict(action.get("payload", {})) if isinstance(action.get("payload", {}), Mapping) else {},
        )

    def dispatch_callback(
        self,
        callback: FeishuParsedCallback | Mapping[str, SerializableValue],
        *,
        control_api: ControlApiLike,
        token: str,
    ) -> dict[str, SerializableValue]:
        if isinstance(callback, FeishuParsedCallback):
            parsed = callback
        elif "type" in callback:
            parsed = FeishuParsedCallback.model_validate(callback)
        else:
            parsed = FeishuParsedCallback(
                type="card_action",
                action=dict(callback.get("action", {})) if isinstance(callback.get("action", {}), Mapping) else {},
                operator_id=str(callback.get("operator_id", "")) or None,
            )
        action = str(parsed.action.get("action", ""))
        if action == "confirm":
            return control_api.confirm_command(
                token,
                str(parsed.action["command_id"]),
                str(parsed.operator_id or ""),
            )
        if action == "cancel":
            return control_api.cancel_command(
                token,
                str(parsed.action["command_id"]),
                str(parsed.operator_id or ""),
            )
        return control_api.submit_command(
            token,
            self.to_command_payload(parsed),
        )
