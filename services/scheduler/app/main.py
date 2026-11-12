from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from datetime import UTC, datetime, timedelta
from itertools import zip_longest

import httpx
from manga_common.config import Settings
from manga_common.http import build_client
from manga_common.logging import configure_logging
from manga_common.source_models import MangaSummary
from pydantic import ValidationError

logger = logging.getLogger("scheduler")


class SchedulerSettings(Settings):
    service_name: str = "scheduler"
    sync_interval_seconds: int = 1800
    sync_batch_size: int = 5
    cleanup_interval_seconds: int = 21600
    notify_new_chapters: bool = True
    catalogue_import_enabled: bool = True
    catalogue_import_interval_seconds: int = 21600
    catalogue_import_per_source_limit: int = 60


class Scheduler:
    def __init__(self, settings: SchedulerSettings) -> None:
        self.settings = settings
        self.client = build_client(settings)
        self.client.headers["X-Internal-Token"] = settings.internal_token
        self._last_cleanup: datetime | None = None
        self._last_catalogue_import: datetime | None = None
        self._stop = asyncio.Event()

    async def _post(self, base: str, path: str, **kwargs) -> dict | None:  # type: ignore[no-untyped-def]
        try:
            response = await self.client.post(f"{base.rstrip('/')}{path}", timeout=120.0, **kwargs)
            if response.status_code >= 400:
                logger.warning(
                    "POST %s%s -> %s %s", base, path, response.status_code, response.text[:200]
                )
                return None
            return response.json() if response.content else {}
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("POST %s%s failed: %s", base, path, exc)
            return None

    async def _get(self, base: str, path: str) -> dict | list | None:
        try:
            response = await self.client.get(f"{base.rstrip('/')}{path}", timeout=30.0)
            if response.status_code >= 400:
                logger.warning(
                    "GET %s%s -> %s %s",
                    base,
                    path,
                    response.status_code,
                    response.text[:200],
                )
                return None
            return response.json() if response.content else {}
        except (httpx.HTTPError, ValueError) as exc:
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
            await self._post(
                self.settings.notifier_url, "/internal/notify/new-chapters", json=payload
            )

    async def import_catalogue(self, now: datetime | None = None) -> None:
        """Populate the catalogue from every enabled source's landing page.

        This is what makes the site usable on a fresh install: no operator has
        to paste a title URL.  Import-summary is idempotent, so repeated runs
        only refresh metadata and add newly discovered titles.

        Sources are processed sequentially so the parser's own per-upstream
        rate limiter stays in control; one broken source never prevents the
        remaining sources from being imported.
        """

        if not self.settings.catalogue_import_enabled:
            logger.debug("catalogue import disabled")
            return

        sources = await self._get(self.settings.parser_url, "/internal/sources")
        if not isinstance(sources, list):
            logger.warning("catalogue import: parser sources unavailable")
            return

        seen: set[tuple[str, str]] = set()
        processed = 0
        imported = 0
        failed_sources: list[str] = []
        limit = self.settings.catalogue_import_per_source_limit

        for raw_source in sources:
            if not isinstance(raw_source, dict):
                continue
            code = str(raw_source.get("code") or "").strip()
            capabilities = raw_source.get("capabilities")
            catalog_enabled = (
                bool(capabilities.get("catalog"))
                if isinstance(capabilities, dict)
                else bool(raw_source.get("catalog"))
            )
            if not code or not raw_source.get("enabled") or not catalog_enabled:
                continue

            processed += 1
            discovered_here = 0
            imported_here = 0
            failed_imports = 0
            try:
                home = await self._get(self.settings.parser_url, f"/internal/home?source={code}")
                if not isinstance(home, dict):
                    raise RuntimeError("empty landing page response")

                lists = [
                    entries
                    for entries in (home.get("popular"), home.get("latest"))
                    if isinstance(entries, list)
                ]
                # Interleave popular/latest so a low per-source cap covers both.
                for group in zip_longest(*lists):
                    if limit > 0 and discovered_here >= limit:
                        break
                    for raw_item in group:
                        if limit > 0 and discovered_here >= limit:
                            break
                        if not isinstance(raw_item, dict):
                            continue

                        payload = dict(raw_item)
                        payload["source"] = str(payload.get("source") or code)
                        try:
                            summary = MangaSummary.model_validate(payload)
                        except ValidationError as exc:
                            logger.warning(
                                "catalogue import: source %s skipped invalid summary: %s",
                                code,
                                exc,
                            )
                            continue

                        source_id = summary.source_id.strip()
                        if not source_id:
                            continue
                        key = (summary.source, source_id)
                        if key in seen:
                            continue
                        seen.add(key)
                        discovered_here += 1

                        result = await self._post(
                            self.settings.catalog_url,
                            "/internal/manga/import-summary",
                            json=summary.model_dump(mode="json"),
                        )
                        if result is None:
                            failed_imports += 1
                        else:
                            imported += 1
                            imported_here += 1
            except Exception as exc:
                failed_sources.append(code)
                logger.warning(
                    "catalogue import: source %s failed: %s (discovered=%d imported=%d)",
                    code,
                    exc,
                    discovered_here,
                    imported_here,
                )
                continue

            if failed_imports:
                logger.warning(
                    "catalogue import: source %s had %d failed imports",
                    code,
                    failed_imports,
                )
            logger.info(
                "catalogue import: source %s processed: discovered=%d imported=%d",
                code,
                discovered_here,
                imported_here,
            )

        self._last_catalogue_import = now or datetime.now(UTC)
        logger.info(
            "catalogue import finished: sources=%d titles_discovered=%d imported=%d "
            "failed_sources=%d",
            processed,
            len(seen),
            imported,
            len(failed_sources),
        )

    def catalogue_import_due(self, now: datetime | None = None) -> bool:
        """Return True when the next catalogue import should run."""

        if not self.settings.catalogue_import_enabled:
            return False
        if self._last_catalogue_import is None:
            return True
        current = now or datetime.now(UTC)
        interval = max(0, self.settings.catalogue_import_interval_seconds)
        return current - self._last_catalogue_import >= timedelta(seconds=interval)

    async def maybe_import_catalogue(self, now: datetime | None = None) -> bool:
        """Import the catalogue if the configured interval has elapsed.

        Returns whether an import was attempted.  The first scheduler tick has
        no previous timestamp, so a fresh deployment fills itself immediately.
        """

        current = now or datetime.now(UTC)
        if not self.catalogue_import_due(current):
            return False
        await self.import_catalogue(now=current)
        return True

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
            except Exception:
                logger.exception("scheduler refresh failed")
            try:
                await self.cleanup()
            except Exception:
                logger.exception("scheduler cleanup failed")
            try:
                await self.maybe_import_catalogue()
            except Exception:
                logger.exception("scheduler catalogue import failed")
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self.settings.sync_interval_seconds
                )
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
