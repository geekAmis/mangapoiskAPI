from __future__ import annotations

import logging
from typing import Any, Protocol

import httpx
from manga_common.config import Settings
from manga_common.http import build_client

logger = logging.getLogger(__name__)


class PushDispatcher(Protocol):
    async def dispatch_chapters(
        self, events: list[dict[str, Any]], recipients: list[dict[str, Any]]
    ) -> dict[str, Any] | None: ...

    async def close(self) -> None: ...


class NotifierPushDispatcher:
    """Forward a chapter fan-out to the notifier's Web Push transport.

    Push delivery is best-effort: the in-app notification is already committed
    before this call, and a notifier outage must never roll it back or make the
    scheduler retry the whole catalogue refresh.
    """

    def __init__(self, settings: Settings) -> None:
        self.client = build_client(settings, base_url=settings.notifier_url.rstrip("/"))
        self.client.headers["X-Internal-Token"] = settings.internal_token
        self.client.headers["Accept"] = "application/json"

    async def dispatch_chapters(
        self, events: list[dict[str, Any]], recipients: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        try:
            response = await self.client.post(
                "/internal/push/chapters",
                json={"events": events, "recipients": recipients},
                timeout=30.0,
            )
        except httpx.HTTPError as exc:
            logger.warning("web push dispatch failed: %s", exc)
            return None
        if response.status_code >= 400:
            logger.warning(
                "web push dispatch rejected: %s %s",
                response.status_code,
                response.text[:300],
            )
            return None
        data = response.json()
        return data if isinstance(data, dict) else None

    async def close(self) -> None:
        await self.client.aclose()
