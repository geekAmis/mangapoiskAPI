from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import zip_longest

import httpx
from manga_common.config import Settings
from manga_common.http import build_client
from manga_common.logging import configure_logging
from manga_common.source_models import MangaDetail, MangaSummary
from pydantic import ValidationError

from .catalogue import CatalogueCrawler

logger = logging.getLogger("scheduler")


class SchedulerSettings(Settings):
    service_name: str = "scheduler"
    sync_interval_seconds: int = 1800
    sync_batch_size: int = 5
    cleanup_interval_seconds: int = 21600
    notify_new_chapters: bool = True
    chapter_notifications_enabled: bool = True
    catalogue_import_enabled: bool = True
    catalogue_import_interval_seconds: int = 21600
    catalogue_import_per_source_limit: int = 60
    catalogue_enrichment_enabled: bool = True
    catalogue_enrichment_concurrency: int = 3
    catalogue_enrichment_limit: int = 30
    # Full-catalogue crawler (MangaPoisk + MangaLib + Remanga).
    catalogue_crawl_enabled: bool = True
    catalogue_sources: str = "mangapoisk,mangalib,remanga"
    catalogue_crawl_delay_seconds: float = 1.75
    catalogue_full_refresh_interval_seconds: int = 604800
    catalogue_incremental_interval_seconds: int = 900
    catalogue_incremental_pages: int = 2
    catalogue_full_retry_seconds: int = 900
    catalogue_enrichment_batch_size: int = 100
    catalogue_page_retries: int = 2
    catalogue_failure_threshold: int = 3
    catalogue_circuit_base_seconds: int = 900
    catalogue_circuit_max_seconds: int = 86400
    catalogue_metadata_refresh_batch: int = 100
    catalogue_metadata_refresh_max_backlog: int = 5000
    catalogue_enrichment_failure_threshold: int = 5
    # 36 requests/minute = one request every 1.67 s, inside the requested
    # 1.5-2 s politeness window (the adapters also enforce this per source).
    scraper_requests_per_minute: int = 36


@dataclass(frozen=True, slots=True)
class EnrichmentTarget:
    source: str
    source_id: str
    url: str | None = None


class Scheduler:
    def __init__(
        self,
        settings: SchedulerSettings,
        *,
        adapter_factory=None,  # type: ignore[no-untyped-def]
        catalogue_sleep=None,  # type: ignore[no-untyped-def]
    ) -> None:
        self.settings = settings
        self.client = build_client(settings)
        self.client.headers["X-Internal-Token"] = settings.internal_token
        self._last_cleanup: datetime | None = None
        self._last_catalogue_import: datetime | None = None
        self._stop = asyncio.Event()
        self._catalogue_task: asyncio.Task | None = None
        self._catalogue_kwargs = {
            "adapter_factory": adapter_factory,
            "sleep": catalogue_sleep,
        }

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

    async def _get(self, base: str, path: str, **kwargs) -> dict | list | None:  # type: ignore[no-untyped-def]
        try:
            response = await self.client.get(f"{base.rstrip('/')}{path}", timeout=30.0, **kwargs)
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
        if events and self.settings.chapter_notifications_enabled:
            await self.dispatch_chapter_notifications(events)

    async def dispatch_chapter_notifications(self, events: list[dict]) -> bool:
        """Fan out imported chapters to followed users (in-app + Web Push).

        The comments service owns the follow table and the in-app dedupe key
        ``(user, manga, chapter)``.  A duplicate delivery from a retried refresh
        is harmless: it creates zero new rows and the notifier skips already
        delivered Web Push chapters.
        """

        if not events:
            return False
        normalized = [
            {
                "manga_id": event["manga_id"],
                "chapter_id": event["chapter_id"],
                "manga_title": event["manga_title"],
                "chapter_label": event["chapter_label"],
                "source": event.get("source"),
                "chapter_url": None,
            }
            for event in events
        ]
        # The comments API caps one request at 50 events; a large import burst
        # must not silently drop everything after the first page.
        success = True
        created = 0
        for index in range(0, len(normalized), 50):
            batch = normalized[index : index + 50]
            result = await self._post(
                self.settings.comments_url,
                "/internal/notifications/chapters",
                json={"events": batch},
            )
            if result is None:
                logger.warning(
                    "chapter notification fan-out failed for events %s-%s",
                    index,
                    index + len(batch),
                )
                success = False
                continue
            created += int(result.get("created", 0))
        logger.info(
            "chapter notifications: events=%s created=%s", len(normalized), created
        )
        return success

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
        enrichment_limit = max(0, self.settings.catalogue_enrichment_limit)
        enrichment_enabled = self.settings.catalogue_enrichment_enabled and enrichment_limit > 0
        enrichment_targets: list[EnrichmentTarget] = []
        enrichment_deferred = 0

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
                            if enrichment_enabled and self._needs_enrichment(result, summary):
                                if len(enrichment_targets) >= enrichment_limit:
                                    enrichment_deferred += 1
                                else:
                                    enrichment_targets.append(
                                        EnrichmentTarget(
                                            source=summary.source,
                                            source_id=source_id,
                                            url=summary.url,
                                        )
                                    )
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

        try:
            enriched, enrichment_failed = await self.enrich_catalogue(enrichment_targets)
        except Exception:
            logger.exception("catalogue enrichment stage failed")
            enriched, enrichment_failed = 0, len(enrichment_targets)
        self._last_catalogue_import = now or datetime.now(UTC)
        logger.info(
            "catalogue import finished: sources=%d titles_discovered=%d imported=%d "
            "failed_sources=%d enrichment_candidates=%d enriched=%d "
            "enrichment_failed=%d enrichment_deferred=%d",
            processed,
            len(seen),
            imported,
            len(failed_sources),
            len(enrichment_targets),
            enriched,
            enrichment_failed,
            enrichment_deferred,
        )

    @staticmethod
    def _needs_enrichment(result: dict, summary: MangaSummary) -> bool:
        """Return True when the stored summary is a dead-end stub.

        The catalog import-summary response is authoritative for stored
        metadata.  If it has an older/opaque shape, we deliberately skip
        enrichment rather than hammering the parser for every title.
        """

        metadata_fields = {"chapters_count", "description", "genres"}
        if not metadata_fields.intersection(result):
            return False
        if result.get("chapters_count") == 0:
            return True
        description = result.get("description", summary.description)
        genres = result.get("genres", summary.genres)
        return not str(description or "").strip() or not genres

    async def enrich_catalogue(self, targets: list[EnrichmentTarget]) -> tuple[int, int]:
        """Hydrate incomplete summaries with the parser's full detail.

        Concurrency is bounded (and capped at three) so the parser's upstream
        rate limiting is not overloaded.  Every target isolates its own
        failure.
        """

        if not targets:
            return 0, 0
        if not self.settings.catalogue_enrichment_enabled:
            return 0, 0
        limit = max(0, self.settings.catalogue_enrichment_limit)
        if limit:
            targets = targets[:limit]
        if not targets:
            return 0, 0
        concurrency = max(1, min(3, self.settings.catalogue_enrichment_concurrency))
        semaphore = asyncio.Semaphore(concurrency)
        results = await asyncio.gather(
            *(self._enrich_target(target, semaphore) for target in targets),
            return_exceptions=True,
        )
        enriched = sum(1 for result in results if result is True)
        failed = len(results) - enriched
        logger.info(
            "catalogue enrichment finished: candidates=%d enriched=%d failed=%d concurrency=%d",
            len(targets),
            enriched,
            failed,
            concurrency,
        )
        return enriched, failed

    async def _enrich_target(self, target: EnrichmentTarget, semaphore: asyncio.Semaphore) -> bool:
        async with semaphore:
            try:
                params = {
                    "source": target.source,
                    "source_id": target.source_id,
                    "chapters_limit": 1000,
                }
                if target.url:
                    params["url"] = target.url
                detail = await self._get(
                    self.settings.parser_url,
                    "/internal/manga",
                    params=params,
                )
                if not isinstance(detail, dict):
                    raise RuntimeError("empty parser detail response")
                parsed = MangaDetail.model_validate(detail)
                if parsed.source != target.source:
                    raise RuntimeError(
                        f"parser returned source {parsed.source!r}, expected {target.source!r}"
                    )
                if parsed.source_id != target.source_id:
                    # The catalogue row was created under the summary identity.
                    # Pin the detail to it so enrichment updates that row instead
                    # of creating a second entry for a normalised source id.
                    logger.warning(
                        "catalogue enrichment: %s/%s parser returned source_id %s; "
                        "pinning to summary id",
                        target.source,
                        target.source_id,
                        parsed.source_id,
                    )
                    parsed = parsed.model_copy(update={"source_id": target.source_id})
                result = await self._post(
                    self.settings.catalog_url,
                    "/internal/manga/import-detail",
                    json=parsed.model_dump(mode="json"),
                )
                if result is None:
                    raise RuntimeError("catalogue rejected detail")
            except Exception as exc:
                logger.warning(
                    "catalogue enrichment: %s/%s failed: %s",
                    target.source,
                    target.source_id,
                    exc,
                )
                return False
        logger.info(
            "catalogue enrichment: %s/%s hydrated",
            target.source,
            target.source_id,
        )
        return True

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

    async def _run_catalogue(self) -> None:
        crawler = CatalogueCrawler(self.settings, self.client, **self._catalogue_kwargs)
        try:
            await crawler.run(self._stop)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("catalogue crawler crashed")

    async def run(self) -> None:
        logger.info("scheduler started; interval=%ss", self.settings.sync_interval_seconds)
        if self.settings.catalogue_crawl_enabled:
            self._catalogue_task = asyncio.create_task(self._run_catalogue())
            logger.info(
                "catalogue crawler started: sources=%s delay=%ss",
                self.settings.catalogue_sources,
                self.settings.catalogue_crawl_delay_seconds,
            )
        try:
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
                if not self.settings.catalogue_crawl_enabled:
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
        finally:
            if self._catalogue_task is not None:
                self._catalogue_task.cancel()
                await asyncio.gather(self._catalogue_task, return_exceptions=True)
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
