"""Resumable, polite catalogue crawler.

The crawler is intentionally independent from the parser HTTP endpoints: the
scheduler needs a *persistent cursor* per source, and it must keep the upstream
request rate at roughly one request every 1.5-2 seconds even across restarts.
It therefore reuses the parser adapters in-process (the scheduler image copies
that small package) and talks to the catalog service for storage/state.

Modes
-----
``full``
    Walk every catalogue page once, importing summaries.  The cursor is stored
    after each page so a restart resumes at the next page instead of page 1.
    After completion the same cursor schedules the next full refresh one week
    later.

``incremental``
    Re-read the first N pages sorted by ``updated`` and ``popular`` every
    10-15 minutes.  It always starts from page 1 and is idempotent.

Enrichment
----------
A separate worker continuously asks the catalog for titles whose
``last_synced_at`` is still NULL (summaries discovered by the crawl) and
imports their detail (description, genres, covers, chapters).  Failures are
retried later without blocking the page crawl.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx
from manga_common.cache import Cache, MemoryCache
from manga_common.config import Settings
from manga_common.errors import (
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    UpstreamError,
)
from manga_common.errors import TimeoutError as UpstreamTimeoutError
from manga_common.http import AsyncRateLimiter, build_client
from manga_common.source_models import MangaDetail, MangaSummary, SourceSearchResult

logger = logging.getLogger("scheduler.catalogue")

Clock = Callable[[], datetime]
Sleeper = Callable[[float], Awaitable[None]]


class CatalogueAdapter(Protocol):
    async def catalogue(
        self, page: int = 1, *, sort: str = "popular", limit: int = 60
    ) -> SourceSearchResult: ...

    async def get_manga(
        self,
        source_id: str = "",
        *,
        url: str | None = None,
        chapters_limit: int = 100,
    ) -> MangaDetail: ...


AdapterFactory = Callable[[str, httpx.AsyncClient, Cache], CatalogueAdapter]


@dataclass(slots=True)
class CrawlReport:
    source: str
    mode: str
    pages: int = 0
    items_seen: int = 0
    imported: int = 0
    completed: bool = False
    error: str | None = None


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


class CatalogueCrawler:
    """One polite crawler per source, sharing an adapter HTTP client."""

    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient,
        *,
        adapter_factory: AdapterFactory | None = None,
        clock: Clock | None = None,
        sleep: Sleeper | None = None,
    ) -> None:
        self.settings = settings
        self.client = client
        self._adapter_factory = adapter_factory
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sleep = sleep or asyncio.sleep
        self._adapter_client: httpx.AsyncClient | None = None
        self._adapters: dict[str, CatalogueAdapter] = {}
        self._cache: Cache = MemoryCache()
        self._retry_after: dict[tuple[str, str], datetime] = {}
        self._enrich_failures: dict[str, int] = {}
        self._enrich_needs_close: set[str] = set()

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    @property
    def sources(self) -> list[str]:
        raw = getattr(self.settings, "catalogue_sources", "mangapoisk,mangalib")
        return [part.strip().lower() for part in str(raw).split(",") if part.strip()]

    @property
    def crawl_delay(self) -> float:
        value = float(getattr(self.settings, "catalogue_crawl_delay_seconds", 1.75))
        return max(0.0, value)

    @property
    def full_interval(self) -> timedelta:
        return timedelta(
            seconds=max(3600, int(getattr(self.settings, "catalogue_full_refresh_interval_seconds", 604800)))
        )

    @property
    def incremental_interval(self) -> timedelta:
        return timedelta(
            seconds=max(
                60, int(getattr(self.settings, "catalogue_incremental_interval_seconds", 900))
            )
        )

    @property
    def incremental_pages(self) -> int:
        return max(1, int(getattr(self.settings, "catalogue_incremental_pages", 2)))

    @property
    def enrichment_concurrency(self) -> int:
        return max(1, min(4, int(getattr(self.settings, "catalogue_enrichment_concurrency", 2))))

    @property
    def enrichment_batch(self) -> int:
        return max(1, min(500, int(getattr(self.settings, "catalogue_enrichment_batch_size", 50))))

    @property
    def retry_delay(self) -> timedelta:
        return timedelta(
            seconds=max(60, int(getattr(self.settings, "catalogue_full_retry_seconds", 900)))
        )

    @property
    def page_retries(self) -> int:
        return max(0, min(5, int(getattr(self.settings, "catalogue_page_retries", 2))))

    @property
    def failure_threshold(self) -> int:
        return max(
            1, min(20, int(getattr(self.settings, "catalogue_failure_threshold", 3)))
        )

    @property
    def circuit_base_seconds(self) -> int:
        return max(
            60,
            int(
                getattr(
                    self.settings,
                    "catalogue_circuit_base_seconds",
                    getattr(self.settings, "catalogue_full_retry_seconds", 900),
                )
            ),
        )

    @property
    def circuit_max_seconds(self) -> int:
        return max(
            self.circuit_base_seconds,
            int(getattr(self.settings, "catalogue_circuit_max_seconds", 86400)),
        )

    @property
    def enrichment_failure_threshold(self) -> int:
        return max(
            1,
            min(
                50,
                int(getattr(self.settings, "catalogue_enrichment_failure_threshold", 5)),
            ),
        )

    @property
    def metadata_refresh_batch(self) -> int:
        return max(
            0,
            min(5000, int(getattr(self.settings, "catalogue_metadata_refresh_batch", 100))),
        )

    @property
    def metadata_refresh_max_backlog(self) -> int:
        return max(
            0,
            int(
                getattr(
                    self.settings, "catalogue_metadata_refresh_max_backlog", 5000
                )
            ),
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def run(self, stop: asyncio.Event) -> None:
        tasks = [
            asyncio.create_task(self._source_guard(source, stop)) for source in self.sources
        ]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if self._adapter_client is not None:
                await self._adapter_client.aclose()
                self._adapter_client = None

    async def _source_guard(self, source: str, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self._run_source(source, stop)
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("catalogue source %s crashed; retrying in 60s", source)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=60)
                except TimeoutError:
                    continue

    async def _run_source(self, source: str, stop: asyncio.Event) -> None:
        adapter = self._build_adapter(source)
        enrichment_enabled = bool(getattr(self.settings, "catalogue_enrichment_enabled", True))
        enrichment = (
            asyncio.create_task(self._enrich_loop(source, adapter, stop))
            if enrichment_enabled
            else None
        )
        try:
            while not stop.is_set():
                blocked_until = await self._blocked_until(source)
                if blocked_until is not None:
                    wait_seconds = min(
                        60.0,
                        max(1.0, (blocked_until - self._clock()).total_seconds()),
                    )
                    logger.info(
                        "catalogue source %s circuit open until %s; sleeping %.0fs",
                        source,
                        blocked_until,
                        wait_seconds,
                    )
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=wait_seconds)
                    except TimeoutError:
                        continue
                    if stop.is_set():
                        break
                    continue
                try:
                    if await self._full_due(source):
                        await self.full_crawl(source, adapter, stop)
                        continue
                    if await self._incremental_due(source):
                        await self.incremental_refresh(source, adapter, stop)
                        continue
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("catalogue crawler %s tick failed", source)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=10)
                except TimeoutError:
                    continue
        finally:
            if enrichment is not None:
                enrichment.cancel()
                await asyncio.gather(enrichment, return_exceptions=True)

    # ------------------------------------------------------------------
    # Adapters / HTTP helpers
    # ------------------------------------------------------------------

    def _build_adapter(self, source: str) -> CatalogueAdapter:
        adapter = self._adapters.get(source)
        if adapter is not None:
            return adapter
        if self._adapter_client is None:
            self._adapter_client = build_client(self.settings)
        if self._adapter_factory is not None:
            adapter = self._adapter_factory(source, self._adapter_client, self._cache)
        else:
            adapter = _default_adapter_factory(
                source, self._adapter_client, self._cache, self.settings
            )
            # The base adapter starts with a full token bucket.  A crawler must
            # not spend that as a 36-request burst, so allow only one token at a
            # time; every subsequent request waits the configured interval.
            limiter = getattr(adapter, "limiter", None)
            if limiter is not None:
                adapter.limiter = AsyncRateLimiter(  # type: ignore[attr-defined]
                    int(getattr(self.settings, "scraper_requests_per_minute", 36)),
                    burst=1,
                )
        self._adapters[source] = adapter
        return adapter

    async def _get(self, path: str, *, params: dict[str, Any] | None = None) -> Any | None:
        try:
            response = await self.client.get(
                f"{self.settings.catalog_url.rstrip('/')}{path}", params=params, timeout=30.0
            )
        except httpx.HTTPError as exc:
            logger.warning("catalogue GET %s failed: %s", path, exc)
            return None
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            logger.warning("catalogue GET %s -> %s %s", path, response.status_code, response.text[:200])
            return None
        return response.json() if response.content else None

    async def _put(self, path: str, payload: dict[str, Any]) -> Any | None:
        try:
            response = await self.client.put(
                f"{self.settings.catalog_url.rstrip('/')}{path}", json=payload, timeout=30.0
            )
        except httpx.HTTPError as exc:
            logger.warning("catalogue PUT %s failed: %s", path, exc)
            return None
        if response.status_code >= 400:
            logger.warning("catalogue PUT %s -> %s %s", path, response.status_code, response.text[:200])
            return None
        return response.json() if response.content else None

    async def _post(
        self, path: str, payload: dict[str, Any], *, params: dict[str, Any] | None = None
    ) -> Any | None:
        try:
            response = await self.client.post(
                f"{self.settings.catalog_url.rstrip('/')}{path}",
                json=payload,
                params=params,
                timeout=120.0,
            )
        except httpx.HTTPError as exc:
            logger.warning("catalogue POST %s failed: %s", path, exc)
            return None
        if response.status_code >= 400:
            logger.warning(
                "catalogue POST %s -> %s %s", path, response.status_code, response.text[:200]
            )
            return None
        return response.json() if response.content else None

    # ------------------------------------------------------------------
    # Crawl state
    # ------------------------------------------------------------------

    async def _get_state(self, source: str, mode: str) -> dict[str, Any] | None:
        data = await self._get(
            f"/internal/crawl-state/{source}", params={"mode": mode}
        )
        return data if isinstance(data, dict) else None

    async def _save_state(self, source: str, mode: str, **values: Any) -> None:
        payload = {"source": source, "mode": mode, **values}
        await self._put(f"/internal/crawl-state/{source}", payload)

    @staticmethod
    def _state_due(state: dict[str, Any] | None, now: datetime) -> bool:
        if state is None:
            return True
        next_run = _as_datetime(state.get("next_run_at"))
        if state.get("status") in {"pending", "running"}:
            return True
        return next_run is None or next_run <= now

    @staticmethod
    def _exception_status(exc: Exception) -> int | None:
        if isinstance(exc, (NotFoundError, ForbiddenError, RateLimitError)):
            return int(exc.status_code)
        if isinstance(exc, UpstreamError) and isinstance(exc.details, dict):
            status = exc.details.get("status_code")
            if isinstance(status, int):
                return status
            if isinstance(status, str) and status.isdigit():
                return int(status)
        return None

    @classmethod
    def _failure_kind(cls, exc: Exception) -> str:
        status = cls._exception_status(exc)
        if isinstance(exc, NotFoundError) or status == 404:
            return "not_found"
        if isinstance(exc, ForbiddenError) or status == 403:
            return "forbidden"
        if isinstance(exc, RateLimitError) or status == 429:
            return "rate_limited"
        if isinstance(exc, UpstreamTimeoutError):
            return "timeout"
        if status is not None and status >= 500:
            return "upstream"
        return "error"

    def _failure_backoff(self, count: int) -> timedelta:
        exponent = min(max(0, count - 1), 12)
        seconds = min(self.circuit_base_seconds * (2**exponent), self.circuit_max_seconds)
        return timedelta(seconds=seconds)

    async def _blocked_until(self, source: str, mode: str = "health") -> datetime | None:
        state = await self._get_state(source, mode)
        if not isinstance(state, dict):
            return None
        next_run = _as_datetime(state.get("next_run_at"))
        if state.get("status") not in {"blocked", "degraded", "failed"}:
            return None
        now = self._clock()
        if next_run is not None and next_run > now:
            return next_run
        return None

    async def _record_source_failure(
        self, source: str, mode: str, exc: Exception, *, permanent: bool = False
    ) -> tuple[int, datetime]:
        health_mode = "enrichment" if mode == "enrichment" else "health"
        health = await self._get_state(source, health_mode) or {}
        count = int(health.get("failure_count") or 0) + 1
        now = self._clock()
        backoff = self.circuit_max_seconds if permanent else None
        delay = (
            timedelta(seconds=backoff)
            if backoff is not None
            else self._failure_backoff(count)
        )
        next_run = now + delay
        threshold = (
            self.enrichment_failure_threshold
            if mode == "enrichment"
            else self.failure_threshold
        )
        blocked = count >= threshold
        kind = self._failure_kind(exc)
        await self._save_state(
            source,
            health_mode,
            page=1,
            status="blocked" if blocked else "degraded",
            last_error=f"{type(exc).__name__}: {exc}"[:4000],
            next_run_at=next_run.isoformat(),
            last_run_at=now.isoformat(),
            last_success_at=health.get("last_success_at"),
            failure_count=count,
            failure_kind=kind,
        )
        logger.warning(
            "catalogue circuit %s/%s failure=%d kind=%s blocked=%s next_run_at=%s",
            source,
            health_mode,
            count,
            kind,
            blocked,
            next_run,
        )
        return count, next_run

    async def _record_source_success(self, source: str, mode: str) -> None:
        health_mode = "enrichment" if mode == "enrichment" else "health"
        health = await self._get_state(source, health_mode)
        if not isinstance(health, dict):
            health = {}
        had_failures = int(health.get("failure_count") or 0) > 0
        now = self._clock()
        await self._save_state(
            source,
            health_mode,
            page=1,
            status="ok",
            last_error=None,
            next_run_at=None,
            last_run_at=now.isoformat(),
            last_success_at=now.isoformat(),
            failure_count=0,
            failure_kind=None,
        )
        if had_failures:
            logger.info("catalogue circuit %s/%s closed after success", source, health_mode)

    async def _full_due(self, source: str) -> bool:
        if await self._blocked_until(source):
            return False
        return self._state_due(await self._get_state(source, "full"), self._clock())

    async def _incremental_due(self, source: str) -> bool:
        if await self._blocked_until(source):
            return False
        return self._state_due(await self._get_state(source, "incremental"), self._clock())

    # ------------------------------------------------------------------
    # Full crawl
    # ------------------------------------------------------------------

    async def _fetch_catalogue_page(
        self, adapter: CatalogueAdapter, page: int, *, sort: str
    ) -> SourceSearchResult:
        """Fetch one page with bounded retries for transient blocks/404s."""

        attempts = self.page_retries + 1
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                return await adapter.catalogue(page, sort=sort)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = exc
                kind = self._failure_kind(exc)
                if kind == "error":
                    raise
                if attempt >= attempts - 1:
                    raise
                delay = min(30.0, 2.0 * (2**attempt) + random.random() * 0.8)
                if kind in {"forbidden", "rate_limited"}:
                    delay = min(30.0, delay * 2)
                logger.warning(
                    "catalogue %s page=%s attempt=%s/%s failed (%s); retrying in %.1fs",
                    adapter.__class__.__name__,
                    page,
                    attempt + 1,
                    attempts,
                    kind,
                    delay,
                )
                await self._sleep(delay)
        raise last_error or RuntimeError("catalogue page fetch failed")

    async def full_crawl(
        self,
        source: str,
        adapter: CatalogueAdapter | None = None,
        stop: asyncio.Event | None = None,
    ) -> CrawlReport:
        adapter = adapter or self._build_adapter(source)
        stop = stop or asyncio.Event()
        now = self._clock()
        state = await self._get_state(source, "full")
        weekly_refresh = False
        if state is not None and state.get("status") == "completed":
            next_run = _as_datetime(state.get("next_run_at"))
            if next_run is not None and next_run > now:
                return CrawlReport(source=source, mode="full", completed=True)
            weekly_refresh = True
            page = 1
            items_seen = 0
            imported = 0
        else:
            page = max(1, int((state or {}).get("page") or 1))
            items_seen = int((state or {}).get("items_seen") or 0)
            imported = int((state or {}).get("items_imported") or 0)

        if weekly_refresh or state is None:
            # Never reset the whole source here: that was the #57 queue storm.
            # The weekly rotation is a bounded batch after a successful pass.
            logger.info(
                "catalogue full %s: starting from page %s (weekly=%s)",
                source,
                page,
                weekly_refresh,
            )

        started = now
        pages_this_run = 0
        seen: set[str] = set()
        report = CrawlReport(source=source, mode="full")
        total_pages = (state or {}).get("total_pages")
        await self._save_state(
            source,
            "full",
            status="running",
            page=page,
            last_error=None,
            last_run_at=now.isoformat(),
            total_pages=total_pages,
            items_seen=items_seen,
            items_imported=imported,
        )

        while not stop.is_set():
            try:
                result = await self._fetch_catalogue_page(adapter, page, sort="popular")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                logger.warning("catalogue full %s page %s failed: %s", source, page, error)
                failure_count, next_run = await self._record_source_failure(
                    source, "full", exc
                )
                await self._save_state(
                    source,
                    "full",
                    status="blocked" if failure_count >= self.failure_threshold else "failed",
                    page=page,
                    last_error=error[:4000],
                    next_run_at=next_run.isoformat(),
                    last_run_at=self._clock().isoformat(),
                    total_pages=total_pages,
                    items_seen=items_seen,
                    items_imported=imported,
                    failure_count=failure_count,
                    failure_kind=self._failure_kind(exc),
                )
                report.error = error
                return report
            else:
                await self._record_source_success(source, "full")

            pages_this_run += 1
            report.pages += 1
            unique = 0
            for summary in result.items:
                key = summary.source_id.strip()
                if not key or key in seen:
                    continue
                seen.add(key)
                unique += 1
                if await self._import_summary(summary):
                    imported += 1
                    report.imported += 1
            items_seen += unique
            report.items_seen = items_seen

            if result.total_pages:
                total_pages = result.total_pages
            elif result.total and result.per_page:
                total_pages = (result.total + result.per_page - 1) // result.per_page

            elapsed = max(0.001, (self._clock() - started).total_seconds())
            rate = pages_this_run / elapsed
            remaining = (
                max(0, int(total_pages) - page) if total_pages is not None else None
            )
            eta = f"{remaining / rate / 60:.1f} min" if remaining is not None and rate else "unknown"
            logger.info(
                "catalogue full %s page=%s/%s items=%s imported=%s "
                "pages/min=%.1f items/min=%.1f eta=%s",
                source,
                page,
                total_pages or "?",
                unique,
                report.imported,
                rate * 60,
                (report.imported / elapsed) * 60,
                eta,
            )

            finished = not result.has_next
            if total_pages is not None and page >= int(total_pages):
                finished = True
            if not result.items and result.has_next and not finished:
                # An unexpectedly empty page before the advertised end: keep
                # the cursor moving rather than declaring the crawl complete.
                page += 1
                await self._save_state(
                    source,
                    "full",
                    status="running",
                    page=page,
                    last_error=None,
                    last_run_at=self._clock().isoformat(),
                    total_pages=total_pages,
                    items_seen=items_seen,
                    items_imported=imported,
                )
                await self._sleep(self.crawl_delay)
                continue
            if finished:
                await self._save_state(
                    source,
                    "full",
                    status="completed",
                    page=page,
                    last_error=None,
                    last_run_at=self._clock().isoformat(),
                    next_run_at=(self._clock() + self.full_interval).isoformat(),
                    total_pages=total_pages or page,
                    items_seen=items_seen,
                    items_imported=imported,
                    failure_count=0,
                    failure_kind=None,
                    last_success_at=self._clock().isoformat(),
                )
                report.completed = True
                logger.info(
                    "catalogue full %s completed: pages=%s items=%s imported=%s "
                    "next_run_at=%s",
                    source,
                    pages_this_run,
                    items_seen,
                    imported,
                    self._clock() + self.full_interval,
                )
                return report

            page += 1
            await self._save_state(
                source,
                "full",
                status="running",
                page=page,
                last_error=None,
                last_run_at=self._clock().isoformat(),
                total_pages=total_pages,
                items_seen=items_seen,
                items_imported=imported,
            )
            await self._sleep(self.crawl_delay)

        return report

    # ------------------------------------------------------------------
    # Incremental refresh
    # ------------------------------------------------------------------

    async def incremental_refresh(
        self,
        source: str,
        adapter: CatalogueAdapter | None = None,
        stop: asyncio.Event | None = None,
    ) -> CrawlReport:
        adapter = adapter or self._build_adapter(source)
        stop = stop or asyncio.Event()
        now = self._clock()
        report = CrawlReport(source=source, mode="incremental")
        seen: set[str] = set()
        try:
            for sort in ("updated", "popular"):
                for page in range(1, self.incremental_pages + 1):
                    if stop.is_set():
                        return report
                    result = await self._fetch_catalogue_page(adapter, page, sort=sort)
                    await self._record_source_success(source, "incremental")
                    report.pages += 1
                    for summary in result.items:
                        key = summary.source_id.strip()
                        if not key or key in seen:
                            continue
                        seen.add(key)
                        report.items_seen += 1
                        if await self._import_summary(summary):
                            report.imported += 1
                    if not result.has_next:
                        break
                    await self._sleep(self.crawl_delay)
            report.completed = True
            await self._rotate_metadata_if_capacity(source)
            await self._save_state(
                source,
                "incremental",
                status="completed",
                page=self.incremental_pages,
                last_error=None,
                last_run_at=now.isoformat(),
                next_run_at=(now + self.incremental_interval).isoformat(),
                total_pages=self.incremental_pages,
                items_seen=report.items_seen,
                items_imported=report.imported,
                failure_count=0,
                failure_kind=None,
                last_success_at=now.isoformat(),
            )
            logger.info(
                "catalogue incremental %s: pages=%s items=%s imported=%s next_run_at=%s",
                source,
                report.pages,
                report.items_seen,
                report.imported,
                now + self.incremental_interval,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            logger.warning("catalogue incremental %s failed: %s", source, error)
            failure_count, next_run = await self._record_source_failure(
                source, "incremental", exc
            )
            await self._save_state(
                source,
                "incremental",
                status="blocked" if failure_count >= self.failure_threshold else "failed",
                page=1,
                last_error=error[:4000],
                last_run_at=now.isoformat(),
                next_run_at=next_run.isoformat(),
                total_pages=self.incremental_pages,
                items_seen=report.items_seen,
                items_imported=report.imported,
                failure_count=failure_count,
                failure_kind=self._failure_kind(exc),
            )
            report.error = error
        return report

    # ------------------------------------------------------------------
    # Summaries and enrichment
    # ------------------------------------------------------------------

    async def _rotate_metadata_if_capacity(self, source: str) -> int:
        """Queue a small metadata-refresh batch only when backlog is low.

        Rotating 100 titles every incremental cycle refreshes the whole
        catalogue over a week without ever issuing the all-rows UPDATE that
        caused the #57 backlog storm.
        """

        if self.metadata_refresh_batch <= 0:
            return 0
        stats = await self._get("/internal/enrichment/stats")
        if not isinstance(stats, dict):
            return 0
        pending = int(stats.get("pending") or 0) + int(stats.get("retrying") or 0)
        if pending > self.metadata_refresh_max_backlog:
            logger.info(
                "catalogue metadata rotation %s deferred: pending=%s > %s",
                source,
                pending,
                self.metadata_refresh_max_backlog,
            )
            return 0
        result = await self._post(
            "/internal/maintenance/rotate-enrichment",
            {},
            params={"source": source, "limit": self.metadata_refresh_batch},
        )
        queued = int(result.get("queued") or 0) if isinstance(result, dict) else 0
        if queued:
            logger.info(
                "catalogue metadata rotation %s queued=%s backlog=%s",
                source,
                queued,
                pending,
            )
        return queued

    async def _import_summary(self, summary: MangaSummary) -> bool:
        payload = summary.model_dump(mode="json")
        result = await self._post("/internal/manga/import-summary", payload)
        return result is not None

    async def _enrich_loop(
        self, source: str, adapter: CatalogueAdapter, stop: asyncio.Event
    ) -> None:
        semaphore = asyncio.Semaphore(self.enrichment_concurrency)
        while not stop.is_set():
            blocked_until = await self._blocked_until(source, "enrichment")
            if blocked_until is not None:
                wait_seconds = min(
                    60.0,
                    max(1.0, (blocked_until - self._clock()).total_seconds()),
                )
                logger.info(
                    "catalogue enrichment %s circuit open until %s; sleeping %.0fs",
                    source,
                    blocked_until,
                    wait_seconds,
                )
                try:
                    await asyncio.wait_for(stop.wait(), timeout=wait_seconds)
                except TimeoutError:
                    continue
                continue
            health = await self._get_state(source, "enrichment")
            if isinstance(health, dict) and int(health.get("failure_count") or 0) > 0:
                self._enrich_needs_close.add(source)
            batch = await self._get(
                "/internal/manga/pending",
                params={"source": source, "limit": self.enrichment_batch},
            )
            items = batch.get("items") if isinstance(batch, dict) else None
            if not items:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=30)
                except TimeoutError:
                    continue
                continue
            results = await asyncio.gather(
                *(
                    self._enrich_one(source, adapter, item, semaphore)
                    for item in items
                    if isinstance(item, dict)
                ),
                return_exceptions=True,
            )
            ok = sum(1 for result in results if result is True)
            failed = len(results) - ok
            logger.info(
                "catalogue enrichment %s batch=%d ok=%d failed=%d concurrency=%d",
                source,
                len(items),
                ok,
                failed,
                self.enrichment_concurrency,
            )
            if len(items) < self.enrichment_batch:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=10)
                except TimeoutError:
                    continue

    async def _enrich_one(
        self,
        source: str,
        adapter: CatalogueAdapter,
        item: dict[str, Any],
        semaphore: asyncio.Semaphore,
    ) -> bool:
        source_id = str(item.get("source_id") or "").strip()
        manga_id = str(item.get("manga_id") or "").strip()
        if not source_id:
            return False
        key = (source, source_id)
        retry_at = self._retry_after.get(key)
        if retry_at is not None and retry_at > self._clock():
            return False
        async with semaphore:
            try:
                detail = await adapter.get_manga(
                    source_id,
                    url=item.get("url"),
                    chapters_limit=1000,
                )
                if detail.source != source:
                    raise RuntimeError(f"adapter returned source {detail.source!r}")
                if detail.source_id != source_id:
                    logger.warning(
                        "catalogue enrichment: %s/%s adapter returned %s; pinning",
                        source,
                        source_id,
                        detail.source_id,
                    )
                    detail = detail.model_copy(update={"source_id": source_id})
                result = await self._post(
                    "/internal/manga/import-detail", detail.model_dump(mode="json")
                )
                if result is None:
                    raise RuntimeError("catalog rejected detail")
                self._retry_after.pop(key, None)
                had_failures = (
                    self._enrich_failures.pop(source, 0) > 0
                    or source in self._enrich_needs_close
                )
                if had_failures:
                    self._enrich_needs_close.discard(source)
                    await self._record_source_success(source, "enrichment")
                logger.info("catalogue enrichment: %s/%s hydrated", source, source_id)
                return True
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                kind = self._failure_kind(exc)
                permanent = kind == "not_found"
                logger.warning(
                    "catalogue enrichment: %s/%s failed (%s): %s",
                    source,
                    source_id,
                    kind,
                    exc,
                )
                if kind in {"forbidden", "rate_limited", "upstream"}:
                    self._enrich_failures[source] = (
                        self._enrich_failures.get(source, 0) + 1
                    )
                    self._enrich_needs_close.add(source)
                    await self._record_source_failure(source, "enrichment", exc)
                if manga_id:
                    recorded = await self._post(
                        f"/internal/manga/{manga_id}/enrichment-failure",
                        {
                            "error": f"{type(exc).__name__}: {exc}"[:4000],
                            "kind": kind,
                            "permanent": permanent,
                        },
                    )
                    if recorded is not None:
                        retry_at = _as_datetime(recorded.get("retry_at"))
                        if retry_at is not None:
                            self._retry_after[key] = retry_at
                            return False
                self._retry_after[key] = self._clock() + timedelta(minutes=10)
                return False


def _default_adapter_factory(
    source: str, client: httpx.AsyncClient, cache: Cache, settings: Settings
) -> CatalogueAdapter:
    """Instantiate a parser adapter in-process.

    The scheduler image copies ``services/parser/app/adapters``; keeping the
    import lazy means unit tests never need BeautifulSoup/lxml unless they
    exercise a real adapter.
    """

    from services.parser.app.adapters.mangalib import MangaLibAdapter
    from services.parser.app.adapters.mangapoisk import MangaPoiskAdapter
    from services.parser.app.adapters.remanga import RemangaAdapter

    adapters = {
        "mangapoisk": MangaPoiskAdapter,
        "mangalib": MangaLibAdapter,
        "remanga": RemangaAdapter,
    }
    adapter_type = adapters.get(source)
    if adapter_type is None:
        raise RuntimeError(f"no catalogue adapter for source '{source}'")
    return adapter_type(client, settings, cache)  # type: ignore[return-value]
