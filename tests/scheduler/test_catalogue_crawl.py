from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from manga_common.errors import NotFoundError, UpstreamError
from manga_common.source_models import (
    ChapterSummary,
    MangaDetail,
    MangaSummary,
    SourceSearchResult,
)
from services.scheduler.app.catalogue import CatalogueCrawler, estimate_eta_seconds
from services.scheduler.app.main import SchedulerSettings

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def summary(source_id: str, title: str | None = None) -> MangaSummary:
    return MangaSummary(
        source="mangapoisk",
        source_id=source_id,
        slug=source_id,
        title=title or f"Title {source_id}",
        poster_url=f"https://cdn.example/{source_id}.jpg",
    )


def detail(source_id: str, *, chapters: int = 2) -> MangaDetail:
    return MangaDetail(
        source="mangapoisk",
        source_id=source_id,
        slug=source_id,
        title=f"Title {source_id}",
        description="Full description",
        genres=["Фэнтези"],
        chapters=[
            ChapterSummary(
                source="mangapoisk",
                source_id=f"{source_id}-{number}",
                manga_source_id=source_id,
                number=str(number),
                title=f"Chapter {number}",
                published_at=NOW + timedelta(days=number),
            )
            for number in range(1, chapters + 1)
        ],
    )


class FakeAdapter:
    def __init__(
        self,
        pages: dict[tuple[int, str], SourceSearchResult],
        details: dict[str, MangaDetail] | None = None,
    ) -> None:
        self.pages = pages
        self.details = details or {}
        self.catalogue_calls: list[tuple[int, str]] = []
        self.detail_calls: list[str] = []

    async def catalogue(
        self, page: int = 1, *, sort: str = "popular", limit: int = 60
    ) -> SourceSearchResult:
        self.catalogue_calls.append((page, sort))
        return self.pages.get(
            (page, sort),
            SourceSearchResult(source="mangapoisk", items=[], page=page, has_next=False),
        )

    async def get_manga(
        self,
        source_id: str = "",
        *,
        url: str | None = None,
        chapters_limit: int = 100,
    ) -> MangaDetail:
        self.detail_calls.append(source_id)
        return self.details.get(source_id, detail(source_id))


class CatalogAPI:
    def __init__(self) -> None:
        self.states: dict[tuple[str, str], dict[str, Any]] = {}
        self.imported_summaries: list[dict[str, Any]] = []
        self.imported_details: list[dict[str, Any]] = []
        self.pending: list[dict[str, Any]] = []
        self.pending_calls = 0
        self.reset_calls = 0
        self.rotate_calls: list[dict[str, Any]] = []
        self.enrichment_stats = {"pending": 0, "retrying": 0}
        self.failure_calls: list[dict[str, Any]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.startswith("/internal/crawl-state/"):
            source = path.rsplit("/", 1)[-1]
            if request.method == "GET":
                mode = request.url.params.get("mode", "full")
                state = self.states.get((source, mode))
                if state is None:
                    return httpx.Response(404, json={"detail": "not found"})
                return httpx.Response(200, json=state)
            payload = json.loads(request.content)
            key = (source, str(payload.get("mode") or "full"))
            state = {"id": "state-1", **payload}
            self.states[key] = state
            return httpx.Response(200, json=state)
        if path == "/internal/manga/import-summary":
            self.imported_summaries.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "manga"})
        if path == "/internal/manga/import-detail":
            self.imported_details.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "manga"})
        if path == "/internal/manga/pending":
            self.pending_calls += 1
            return httpx.Response(200, json={"items": self.pending, "total": len(self.pending)})
        if path == "/internal/maintenance/reset-enrichment":
            self.reset_calls += 1
            return httpx.Response(200, json={"queued": 1})
        if path == "/internal/maintenance/rotate-enrichment":
            self.rotate_calls.append(dict(request.url.params))
            return httpx.Response(200, json={"queued": 1})
        if path == "/internal/enrichment/stats":
            return httpx.Response(200, json=self.enrichment_stats)
        if path.startswith("/internal/manga/") and path.endswith("/enrichment-failure"):
            payload = json.loads(request.content)
            payload["manga_id"] = path.split("/")[3]
            self.failure_calls.append(payload)
            return httpx.Response(
                200,
                json={
                    "manga_id": payload["manga_id"],
                    "attempts": len(self.failure_calls),
                    "retry_at": (NOW + timedelta(minutes=10)).isoformat(),
                },
            )
        return httpx.Response(404, json={"detail": "unexpected"})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


def settings(**overrides: Any) -> SchedulerSettings:
    values: dict[str, Any] = {
        "service_name": "scheduler-test",
        "environment": "test",
        "catalog_url": "http://catalog.test",
        "catalogue_sources": "mangapoisk",
        "catalogue_crawl_delay_seconds": 1.75,
        "catalogue_full_refresh_interval_seconds": 604800,
        "catalogue_incremental_interval_seconds": 900,
        "catalogue_incremental_pages": 2,
    }
    values.update(overrides)
    return SchedulerSettings(_env_file=None, **values)


def make_crawler(
    api: CatalogAPI,
    adapter: FakeAdapter,
    *,
    sleep_calls: list[float] | None = None,
    clock=lambda: NOW,  # type: ignore[no-untyped-def]
    scheduler_settings: SchedulerSettings | None = None,
) -> CatalogueCrawler:
    sleep_calls = sleep_calls if sleep_calls is not None else []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    def factory(source: str, client: httpx.AsyncClient, cache: Any) -> FakeAdapter:
        assert source == "mangapoisk"
        return adapter

    return CatalogueCrawler(
        scheduler_settings or settings(),
        api.client(),
        adapter_factory=factory,
        sleep=fake_sleep,
        clock=clock,
    )


@pytest.mark.asyncio
async def test_full_crawl_paginates_dedupes_and_persists_state() -> None:
    api = CatalogAPI()
    adapter = FakeAdapter(
        {
            (1, "popular"): SourceSearchResult(
                source="mangapoisk",
                items=[summary("1"), summary("1"), summary("2")],
                page=1,
                total=3,
                has_next=True,
                total_pages=2,
                per_page=2,
            ),
            (2, "popular"): SourceSearchResult(
                source="mangapoisk",
                items=[summary("3")],
                page=2,
                total=3,
                has_next=False,
                total_pages=2,
                per_page=2,
            ),
        }
    )
    sleeps: list[float] = []
    crawler = make_crawler(api, adapter, sleep_calls=sleeps)

    report = await crawler.full_crawl("mangapoisk", adapter)

    assert report.completed is True
    assert report.pages == 2
    assert report.imported == 3
    assert [item["source_id"] for item in api.imported_summaries] == ["1", "2", "3"]
    assert adapter.catalogue_calls == [(1, "popular"), (2, "popular")]
    assert sleeps == [1.75]
    state = api.states[("mangapoisk", "full")]
    assert state["status"] == "completed"
    assert state["page"] == 2
    assert state["total_pages"] == 2
    assert state["items_seen"] == 3
    assert state["items_imported"] == 3
    assert state["next_run_at"]
    if crawler._adapter_client is not None:
        await crawler._adapter_client.aclose()
    await crawler.client.aclose()


@pytest.mark.asyncio
async def test_full_crawl_resumes_at_saved_page() -> None:
    api = CatalogAPI()
    api.states[("mangapoisk", "full")] = {
        "id": "state-1",
        "source": "mangapoisk",
        "mode": "full",
        "page": 2,
        "status": "running",
        "last_error": "temporary",
        "total_pages": 2,
        "items_seen": 2,
        "items_imported": 2,
    }
    adapter = FakeAdapter(
        {
            (1, "popular"): SourceSearchResult(
                source="mangapoisk", items=[summary("1")], page=1, has_next=True
            ),
            (2, "popular"): SourceSearchResult(
                source="mangapoisk",
                items=[summary("2")],
                page=2,
                total=2,
                has_next=False,
                total_pages=2,
            ),
        }
    )
    crawler = make_crawler(api, adapter)

    report = await crawler.full_crawl("mangapoisk", adapter)

    assert report.completed is True
    assert adapter.catalogue_calls == [(2, "popular")]
    assert [item["source_id"] for item in api.imported_summaries] == ["2"]
    await crawler.client.aclose()


@pytest.mark.asyncio
async def test_incremental_queues_bounded_metadata_rotation() -> None:
    api = CatalogAPI()
    api.enrichment_stats = {"pending": 10, "retrying": 0}
    adapter = FakeAdapter(
        {
            (1, "updated"): SourceSearchResult(
                source="mangapoisk", items=[summary("1")], page=1, has_next=False
            ),
            (1, "popular"): SourceSearchResult(
                source="mangapoisk", items=[summary("1")], page=1, has_next=False
            ),
        }
    )
    crawler = make_crawler(api, adapter)

    report = await crawler.incremental_refresh("mangapoisk", adapter)

    assert report.completed is True
    assert api.rotate_calls == [{"source": "mangapoisk", "limit": "100"}]
    state = api.states[("mangapoisk", "incremental")]
    assert state["status"] == "completed"
    await crawler.client.aclose()


@pytest.mark.asyncio
async def test_incremental_rotation_deferred_when_backlog_large() -> None:
    api = CatalogAPI()
    api.enrichment_stats = {"pending": 6000, "retrying": 0}
    adapter = FakeAdapter(
        {
            (1, "updated"): SourceSearchResult(
                source="mangapoisk", items=[summary("1")], page=1, has_next=False
            ),
            (1, "popular"): SourceSearchResult(
                source="mangapoisk", items=[summary("1")], page=1, has_next=False
            ),
        }
    )
    crawler = make_crawler(api, adapter)

    report = await crawler.incremental_refresh("mangapoisk", adapter)

    assert report.completed is True
    assert api.rotate_calls == []
    await crawler.client.aclose()


@pytest.mark.asyncio
async def test_documented_empty_end_page_completes_normally() -> None:
    api = CatalogAPI()
    adapter = FakeAdapter(
        {
            (1, "popular"): SourceSearchResult(
                source="mangapoisk", items=[], page=1, has_next=False
            )
        }
    )
    crawler = make_crawler(api, adapter)

    report = await crawler.full_crawl("mangapoisk", adapter)

    assert report.completed is True
    assert report.error is None
    state = api.states[("mangapoisk", "full")]
    assert state["status"] == "completed"
    assert state["failure_count"] == 0
    health = api.states[("mangapoisk", "health")]
    assert health["status"] == "ok"
    assert health["last_success_at"]
    await crawler.client.aclose()


class FlakyAdapter(FakeAdapter):
    def __init__(self, failures: list[Exception], success: SourceSearchResult) -> None:
        super().__init__({})
        self.failures = list(failures)
        self.success = success
        self.calls = 0

    async def catalogue(self, page: int = 1, *, sort: str = "popular", limit: int = 60):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return self.success


@pytest.mark.asyncio
async def test_transient_404_then_success_does_not_open_circuit() -> None:
    api = CatalogAPI()
    adapter = FlakyAdapter(
        [NotFoundError("MangaLib: resource not found", code="not_found")],
        SourceSearchResult(
            source="mangapoisk",
            items=[summary("1")],
            page=1,
            has_next=False,
            total_pages=1,
        ),
    )
    sleeps: list[float] = []
    crawler = make_crawler(api, adapter, sleep_calls=sleeps)

    report = await crawler.full_crawl("mangapoisk", adapter)

    assert report.completed is True
    assert adapter.calls == 2
    assert sleeps and sleeps[0] >= 2.0
    health = api.states[("mangapoisk", "health")]
    assert health["failure_count"] == 0
    assert health["status"] == "ok"
    await crawler.client.aclose()


@pytest.mark.asyncio
async def test_transient_403_then_success_does_not_open_circuit() -> None:
    api = CatalogAPI()
    blocked = UpstreamError(
        "Upstream returned HTTP 403", details={"status_code": 403}
    )
    adapter = FlakyAdapter(
        [blocked, blocked],
        SourceSearchResult(
            source="mangapoisk",
            items=[summary("1")],
            page=1,
            has_next=False,
            total_pages=1,
        ),
    )
    sleeps: list[float] = []
    crawler = make_crawler(api, adapter, sleep_calls=sleeps)

    report = await crawler.full_crawl("mangapoisk", adapter)

    assert report.completed is True
    assert adapter.calls == 3
    assert len(sleeps) >= 2
    assert api.states[("mangapoisk", "health")]["failure_count"] == 0
    await crawler.client.aclose()


@pytest.mark.asyncio
async def test_persistent_404_opens_circuit_and_success_closes_it() -> None:
    api = CatalogAPI()
    current = [NOW]

    class ToggleAdapter(FakeAdapter):
        def __init__(self) -> None:
            super().__init__({})
            self.fail = True
            self.calls = 0

        async def catalogue(self, page: int = 1, *, sort: str = "popular", limit: int = 60):
            self.calls += 1
            if self.fail:
                raise NotFoundError("MangaLib: resource not found", code="not_found")
            return SourceSearchResult(
                source="mangapoisk",
                items=[summary("1")],
                page=1,
                has_next=False,
                total_pages=1,
            )

    adapter = ToggleAdapter()
    crawler = make_crawler(
        api,
        adapter,
        clock=lambda: current[0],
        scheduler_settings=settings(
            catalogue_page_retries=0,
            catalogue_failure_threshold=2,
            catalogue_circuit_base_seconds=60,
            catalogue_circuit_max_seconds=600,
        ),
    )

    first = await crawler.full_crawl("mangapoisk", adapter)
    assert first.completed is False
    assert api.states[("mangapoisk", "health")]["failure_count"] == 1
    assert await crawler._blocked_until("mangapoisk") is not None

    current[0] = NOW + timedelta(seconds=61)
    assert await crawler._blocked_until("mangapoisk") is None
    second = await crawler.full_crawl("mangapoisk", adapter)
    assert second.completed is False
    health = api.states[("mangapoisk", "health")]
    assert health["failure_count"] == 2
    assert health["status"] == "blocked"
    assert health["failure_kind"] == "not_found"
    assert await crawler._blocked_until("mangapoisk") is not None

    current[0] = NOW + timedelta(seconds=61 + 121)
    assert await crawler._blocked_until("mangapoisk") is None
    adapter.fail = False
    third = await crawler.full_crawl("mangapoisk", adapter)
    assert third.completed is True
    health = api.states[("mangapoisk", "health")]
    assert health["status"] == "ok"
    assert health["failure_count"] == 0
    assert health["last_success_at"]
    await crawler.client.aclose()


@pytest.mark.asyncio
async def test_incremental_403_opens_circuit_and_blocks_retry_loop() -> None:
    api = CatalogAPI()
    current = [NOW]

    class ToggleAdapter(FakeAdapter):
        def __init__(self) -> None:
            super().__init__({})
            self.fail = True

        async def catalogue(self, page: int = 1, *, sort: str = "popular", limit: int = 60):
            if self.fail:
                raise UpstreamError(
                    "Upstream returned HTTP 403", details={"status_code": 403}
                )
            return SourceSearchResult(
                source="mangapoisk", items=[summary("1")], page=1, has_next=False
            )

    adapter = ToggleAdapter()
    crawler = make_crawler(
        api,
        adapter,
        clock=lambda: current[0],
        scheduler_settings=settings(
            catalogue_page_retries=0,
            catalogue_failure_threshold=1,
            catalogue_circuit_base_seconds=60,
        ),
    )

    report = await crawler.incremental_refresh("mangapoisk", adapter)
    assert report.completed is False
    state = api.states[("mangapoisk", "incremental")]
    assert state["status"] == "blocked"
    assert state["failure_kind"] == "forbidden"
    assert await crawler._blocked_until("mangapoisk") is not None

    current[0] = NOW + timedelta(seconds=61)
    adapter.fail = False
    report = await crawler.incremental_refresh("mangapoisk", adapter)
    assert report.completed is True
    health = api.states[("mangapoisk", "health")]
    assert health["status"] == "ok"
    assert health["failure_count"] == 0
    await crawler.client.aclose()


@pytest.mark.asyncio
async def test_full_crawl_records_failure_for_retry() -> None:
    class BrokenAdapter(FakeAdapter):
        async def catalogue(self, page: int = 1, *, sort: str = "popular", limit: int = 60):
            raise RuntimeError("upstream exploded")

    api = CatalogAPI()
    adapter = BrokenAdapter({})
    crawler = make_crawler(api, adapter)

    report = await crawler.full_crawl("mangapoisk", adapter)

    assert report.completed is False
    assert "upstream exploded" in (report.error or "")
    state = api.states[("mangapoisk", "full")]
    assert state["status"] == "failed"
    assert "upstream exploded" in state["last_error"]
    assert state["next_run_at"]
    await crawler.client.aclose()


@pytest.mark.asyncio
async def test_incremental_refresh_reuses_updated_and_popular_pages() -> None:
    api = CatalogAPI()
    adapter = FakeAdapter(
        {
            (1, "updated"): SourceSearchResult(
                source="mangapoisk", items=[summary("1")], page=1, has_next=True
            ),
            (2, "updated"): SourceSearchResult(
                source="mangapoisk", items=[summary("2")], page=2, has_next=False
            ),
            (1, "popular"): SourceSearchResult(
                source="mangapoisk", items=[summary("1"), summary("3")], page=1, has_next=False
            ),
        }
    )
    crawler = make_crawler(api, adapter)

    report = await crawler.incremental_refresh("mangapoisk", adapter)

    assert report.completed is True
    assert [item["source_id"] for item in api.imported_summaries] == ["1", "2", "3"]
    assert adapter.catalogue_calls == [
        (1, "updated"),
        (2, "updated"),
        (1, "popular"),
    ]
    state = api.states[("mangapoisk", "incremental")]
    assert state["status"] == "completed"
    assert state["next_run_at"]
    await crawler.client.aclose()


@pytest.mark.asyncio
async def test_enrichment_imports_detail_and_retries_failures() -> None:
    api = CatalogAPI()
    adapter = FakeAdapter({})
    crawler = make_crawler(api, adapter)
    semaphore = asyncio.Semaphore(1)

    ok = await crawler._enrich_one(
        "mangapoisk",
        adapter,
        {"source_id": "1", "url": "https://mangapoisk.me/manga/1"},
        semaphore,
    )
    assert ok is True
    assert adapter.detail_calls == ["1"]
    assert api.imported_details[0]["source_id"] == "1"
    assert len(api.imported_details[0]["chapters"]) == 2

    class BrokenAdapter(FakeAdapter):
        async def get_manga(self, source_id: str = "", *, url=None, chapters_limit=100):
            raise RuntimeError("detail failed")

    broken = BrokenAdapter({})
    failed = await crawler._enrich_one(
        "mangapoisk", broken, {"source_id": "2"}, semaphore
    )
    assert failed is False
    assert ("mangapoisk", "2") in crawler._retry_after
    # A second attempt before the retry window is skipped without a request.
    assert (
        await crawler._enrich_one("mangapoisk", broken, {"source_id": "2"}, semaphore)
        is False
    )
    await crawler.client.aclose()


def test_estimate_eta_seconds_uses_page_rate() -> None:
    assert (
        estimate_eta_seconds(
            page=10, total_pages=100, pages_this_run=10, elapsed_seconds=60
        )
        == 540
    )
    assert (
        estimate_eta_seconds(
            page=100, total_pages=100, pages_this_run=100, elapsed_seconds=600
        )
        == 0
    )
    assert (
        estimate_eta_seconds(
            page=10, total_pages=None, pages_this_run=10, elapsed_seconds=60
        )
        is None
    )
    assert (
        estimate_eta_seconds(
            page=10, total_pages=100, pages_this_run=0, elapsed_seconds=60
        )
        is None
    )


def test_default_crawl_settings_are_polite() -> None:
    for variable in (
        "CATALOGUE_CRAWL_ENABLED",
        "CATALOGUE_SOURCES",
        "CATALOGUE_CRAWL_DELAY_SECONDS",
        "CATALOGUE_FULL_REFRESH_INTERVAL_SECONDS",
        "CATALOGUE_INCREMENTAL_INTERVAL_SECONDS",
        "CATALOGUE_INCREMENTAL_PAGES",
    ):
        os.environ.pop(variable, None)
    settings = SchedulerSettings(_env_file=None)
    assert settings.catalogue_crawl_enabled is True
    configured = {part.strip() for part in settings.catalogue_sources.split(",")}
    assert {"mangapoisk", "mangalib"} <= configured
    assert 1.5 <= settings.catalogue_crawl_delay_seconds <= 2.0
    assert settings.catalogue_full_refresh_interval_seconds == 7 * 24 * 3600
    assert 600 <= settings.catalogue_incremental_interval_seconds <= 900
    assert settings.catalogue_incremental_pages >= 1
