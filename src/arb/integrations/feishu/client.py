"""Feishu API client."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping

from arb.integrations.feishu.schemas import FeishuCard, FeishuTransportRequest
from arb.schemas.base import SerializableValue

Transport = Callable[[FeishuTransportRequest], Mapping[str, SerializableValue]]


class FeishuClient:
    """Small Feishu client for token and message sending."""

    token_url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    message_url = "https://open.feishu.cn/open-apis/im/v1/messages"

    def __init__(self, app_id: str, app_secret: str, transport: Transport) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.transport = transport
        self._tenant_access_token: str | None = None
        self._expires_at: float = 0

    def get_tenant_access_token(self, *, now: float | None = None) -> str:
        current = now or time.time()
        if self._tenant_access_token and current < self._expires_at:
            return self._tenant_access_token
        return self.refresh_token(now=current)

    def refresh_token(self, *, now: float | None = None) -> str:
        payload = self._request_with_retry(
            FeishuTransportRequest(
                method="POST",
                url=self.token_url,
                json_body={"app_id": self.app_id, "app_secret": self.app_secret},
            )
        )
        token = str(payload["tenant_access_token"])
        expires_in = int(payload.get("expire", payload.get("expires_in", 7200)))
        current = now or time.time()
        self._tenant_access_token = token
        self._expires_at = current + expires_in - 60
        return token

    def send_message(
        self,
        *,
        receive_id: str,
        content: dict[str, SerializableValue],
        msg_type: str = "text",
    ) -> dict[str, SerializableValue]:
        token = self.get_tenant_access_token()
        return self._request_with_retry(
            FeishuTransportRequest(
                method="POST",
                url=self.message_url,
                headers={"Authorization": f"Bearer {token}"},
                params={"receive_id_type": "open_id"},
                json_body={
                    "receive_id": receive_id,
                    "msg_type": msg_type,
                    "content": json.dumps(content, separators=(",", ":"), ensure_ascii=True),
                },
            )
        )

    def send_card(self, *, receive_id: str, card: FeishuCard | Mapping[str, SerializableValue]) -> dict[str, SerializableValue]:
        payload = card.to_dict() if isinstance(card, FeishuCard) else dict(card)
        return self.send_message(receive_id=receive_id, content={"card": payload}, msg_type="interactive")

    def _request_with_retry(self, request: FeishuTransportRequest) -> dict[str, SerializableValue]:
        attempts = 0
        while True:
            attempts += 1
            try:
                return dict(self.transport(request))
            except RuntimeError:
                if attempts >= 2:
                    raise
