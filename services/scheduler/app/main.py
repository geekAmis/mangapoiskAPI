from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from datetime import UTC, datetime, timedelta

import httpx
from manga_common.config import Settings
from manga_common.http import build_client
from manga_common.logging import configure_logging

logger = logging.getLogger("scheduler")


class SchedulerSettings(Settings):
    service_name: str = "scheduler"
    sync_interval_seconds: int = 1800
    sync_batch_size: int = 5
    cleanup_interval_seconds: int = 21600
    notify_new_chapters: bool = True


class Scheduler:
    def __init__(self, settings: SchedulerSettings) -> None:
        self.settings = settings
        self.client = build_client(settings)
        self.client.headers["X-Internal-Token"] = settings.internal_token
        self._last_cleanup: datetime | None = None
        self._stop = asyncio.Event()

    async def _post(self, base: str, path: str, **kwargs) -> dict | None:  # type: ignore[no-untyped-def]
        try:
            response = await self.client.post(f"{base.rstrip('/')}{path}", timeout=120.0, **kwargs)
            if response.status_code >= 400:
                logger.warning("POST %s%s -> %s %s", base, path, response.status_code, response.text[:200])
                return None
            return response.json() if response.content else {}
        except httpx.HTTPError as exc:
            logger.warning("POST %s%s failed: %s", base, path, exc)
            return None

    async def _get(self, base: str, path: str) -> dict | None:
        try:
            response = await self.client.get(f"{base.rstrip('/')}{path}", timeout=30.0)
            if response.status_code >= 400:
                return None
            return response.json() if response.content else {}
        except httpx.HTTPError as exc:
            logger.warning("GET %s%s failed: %s", base, path, exc)
            return None

    async def refresh(self) -> None:
        result = await self._post(
            self.settings.catalog_url,
            "/internal/maintenance/refresh",
            params={"limit": self.settings.sync_batch_size},
        )
        if not result:
            return
        logger.info(
            "catalogue refreshed: %s ok, %s failed, %s new chapters",
            result.get("refreshed", 0),
            result.get("failed", 0),
            len(result.get("new_chapters", [])),
        )
        events = result.get("new_chapters") or []
        if events and self.settings.notify_new_chapters:
            payload = {
                "events": [
                    {
                        "manga_title": event["manga_title"],
                        "chapter_label": event["chapter_label"],
                        "source": event["source"],
                        "url": f"{self.settings.public_web_url.rstrip('/')}/manga/{event['manga_id']}",
                    }
                    for event in events[:25]
                ]
            }
            await self._post(self.settings.notifier_url, "/internal/notify/new-chapters", json=payload)

    async def cleanup(self) -> None:
        now = datetime.now(UTC)
        if self._last_cleanup and now - self._last_cleanup < timedelta(
            seconds=self.settings.cleanup_interval_seconds
        ):
            return
        self._last_cleanup = now
        result = await self._post(self.settings.media_url, "/internal/maintenance/cleanup")
        if result:
            logger.info("media cleanup: %s", result.get("message"))

    async def run(self) -> None:
        logger.info("scheduler started; interval=%ss", self.settings.sync_interval_seconds)
        await asyncio.sleep(8)
        while not self._stop.is_set():
            try:
                await self.refresh()
                await self.cleanup()
            except Exception:
                logger.exception("scheduler iteration failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.settings.sync_interval_seconds)
            except TimeoutError:
                continue
        await self.client.aclose()
        logger.info("scheduler stopped")

    def stop(self) -> None:
        self._stop.set()


async def main() -> None:
    settings = SchedulerSettings()
    configure_logging(settings.log_level, settings.log_json, settings.service_name)
    scheduler = Scheduler(settings)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, scheduler.stop)
    await scheduler.run()


if __name__ == "__main__":
    asyncio.run(main())
