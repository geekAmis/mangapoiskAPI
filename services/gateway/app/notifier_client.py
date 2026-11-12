from __future__ import annotations

from typing import Any

from .clients import InternalClient


class NotifierClient(InternalClient):
    service_code = "notifier"

    async def push_config(self) -> dict[str, Any]:
        return await self.request("GET", "/internal/push/public-key")

    async def subscribe(
        self,
        *,
        user_id: str,
        endpoint: str,
        p256dh: str,
        auth: str,
        user_agent: str | None,
    ) -> dict[str, Any]:
        return await self.request(
            "POST",
            "/internal/push/subscribe",
            json={
                "user_id": user_id,
                "endpoint": endpoint,
                "keys": {"p256dh": p256dh, "auth": auth},
                "user_agent": user_agent,
            },
        )

    async def unsubscribe(self, *, user_id: str, endpoint: str) -> dict[str, Any]:
        return await self.request(
            "DELETE",
            "/internal/push/subscribe",
            json={"user_id": user_id, "endpoint": endpoint},
        )

    async def status(self, user_id: str) -> dict[str, Any]:
        return await self.request(
            "GET", "/internal/push/status", params={"user_id": user_id}
        )
