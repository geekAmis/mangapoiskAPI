from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from services.scheduler.app import main as scheduler_main
from services.scheduler.app.main import Scheduler, SchedulerSettings

FIXED_NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def source(
    code: str,
    *,
    enabled: bool = True,
    catalog: bool = True,
) -> dict[str, Any]:
    return {
        "code": code,
        "name": code.title(),
        "base_url": f"https://{code}.example",
        "enabled": enabled,
        "capabilities": {"catalog": catalog, "latest": catalog},
    }


def summary(
    source_code: str | None, source_id: str, title: str, *, url: str | None = None
) -> dict[str, Any]:
    item: dict[str, Any] = {"source_id": source_id, "title": title}
    if source_code is not None:
        item["source"] = source_code
    if url is not None:
        item["url"] = url
    return item


def stored_summary(
    source_id: str,
    *,
    source_code: str = "reader",
    chapters_count: int = 0,
    description: str | None = None,
    genres: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": f"manga-{source_id}",
        "source": source_code,
        "source_id": source_id,
        "title": f"Title {source_id}",
        "description": description,
        "genres": genres or [],
        "chapters_count": chapters_count,
    }


def parser_detail(
    source_id: str,
    *,
    source_code: str = "reader",
    chapters: int = 1,
) -> dict[str, Any]:
    return {
        "source": source_code,
        "source_id": source_id,
        "title": f"Title {source_id}",
        "description": f"Full description for {source_id}",
        "genres": ["Фэнтези", "Приключения"],
        "chapters": [
            {
                "source": source_code,
                "source_id": f"{source_id}-{number}",
                "manga_source_id": source_id,
                "number": str(number),
                "title": f"Chapter {number}",
            }
            for number in range(1, chapters + 1)
        ],
    }


def make_scheduler(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
    **overrides: Any,
) -> Scheduler:
    def fake_build_client(settings: SchedulerSettings, *, base_url: str = "") -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=base_url)

    monkeypatch.setattr(scheduler_main, "build_client", fake_build_client)
    values: dict[str, Any] = {
        "service_name": "scheduler-test",
        "environment": "test",
        "parser_url": "http://parser.test",
        "catalog_url": "http://catalog.test",
        "catalogue_import_enabled": True,
        "catalogue_import_interval_seconds": 3600,
        "catalogue_import_per_source_limit": 60,
        "catalogue_enrichment_enabled": True,
        "catalogue_enrichment_concurrency": 3,
        "catalogue_enrichment_limit": 30,
    }
    values.update(overrides)
    settings = SchedulerSettings(_env_file=None, **values)
    return Scheduler(settings)


async def close(scheduler: Scheduler) -> None:
    await scheduler.client.aclose()


@pytest.mark.asyncio
async def test_disabled_and_non_catalog_sources_are_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json=[
                source("disabled", enabled=False),
                source("no-catalog", catalog=False),
            ],
        )

    scheduler = make_scheduler(monkeypatch, handler)
    try:
        await scheduler.import_catalogue(now=FIXED_NOW)
    finally:
        await close(scheduler)

    assert [request.url.path for request in calls] == ["/internal/sources"]
    assert scheduler._last_catalogue_import == FIXED_NOW


@pytest.mark.asyncio
async def test_duplicate_summaries_are_deduped_across_popular_and_latest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imported: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/internal/sources":
            return httpx.Response(200, json=[source("reader")])
        if request.url.path == "/internal/home":
            assert request.url.params["source"] == "reader"
            return httpx.Response(
                200,
                json={
                    "source": "reader",
                    "popular": [
                        summary("reader", "1", "One"),
                        summary(None, "1", "One duplicate"),
                    ],
                    "latest": [
                        summary("reader", "1", "One latest"),
                        summary("reader", "2", "Two"),
                        summary("reader", "2", "Two duplicate"),
                    ],
                },
            )
        if request.url.path == "/internal/manga/import-summary":
            imported.append(json.loads(request.content))
            return httpx.Response(200, json={"id": f"manga-{len(imported)}"})
        raise AssertionError(f"unexpected request: {request.url}")

    scheduler = make_scheduler(monkeypatch, handler)
    try:
        await scheduler.import_catalogue(now=FIXED_NOW)
    finally:
        await close(scheduler)

    assert [item["source_id"] for item in imported] == ["1", "2"]
    assert all(item["source"] == "reader" for item in imported)
    assert [item["title"] for item in imported] == ["One", "Two"]


@pytest.mark.asyncio
async def test_one_failing_source_does_not_stop_the_others(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    imported: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/internal/sources":
            return httpx.Response(200, json=[source("broken"), source("works")])
        if request.url.path == "/internal/home":
            if request.url.params["source"] == "broken":
                return httpx.Response(503, json={"detail": "upstream unavailable"})
            return httpx.Response(
                200,
                json={
                    "source": "works",
                    "popular": [summary("works", "42", "Working title")],
                    "latest": [],
                },
            )
        if request.url.path == "/internal/manga/import-summary":
            imported.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "manga-42"})
        raise AssertionError(f"unexpected request: {request.url}")

    scheduler = make_scheduler(monkeypatch, handler)
    try:
        with caplog.at_level(logging.INFO, logger="scheduler"):
            await scheduler.import_catalogue(now=FIXED_NOW)
    finally:
        await close(scheduler)

    assert [item["source_id"] for item in imported] == ["42"]
    assert "source broken failed" in caplog.text
    assert "sources=2 titles_discovered=1 imported=1 failed_sources=1" in caplog.text


@pytest.mark.asyncio
async def test_catalog_failure_for_one_title_does_not_stop_the_source(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    imported: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/internal/sources":
            return httpx.Response(200, json=[source("reader")])
        if request.url.path == "/internal/home":
            return httpx.Response(
                200,
                json={
                    "source": "reader",
                    "popular": [
                        summary("reader", "1", "Broken import"),
                        summary("reader", "2", "Healthy import"),
                    ],
                    "latest": [],
                },
            )
        if request.url.path == "/internal/manga/import-summary":
            payload = json.loads(request.content)
            if payload["source_id"] == "1":
                return httpx.Response(500, json={"detail": "database error"})
            imported.append(payload)
            return httpx.Response(200, json={"id": "manga-2"})
        raise AssertionError(f"unexpected request: {request.url}")

    scheduler = make_scheduler(monkeypatch, handler)
    try:
        with caplog.at_level(logging.INFO, logger="scheduler"):
            await scheduler.import_catalogue(now=FIXED_NOW)
    finally:
        await close(scheduler)

    assert [item["source_id"] for item in imported] == ["2"]
    assert "source reader had 1 failed imports" in caplog.text
    assert "source reader processed: discovered=2 imported=1" in caplog.text


@pytest.mark.asyncio
async def test_per_source_limit_caps_discovered_titles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imported: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/internal/sources":
            return httpx.Response(200, json=[source("reader")])
        if request.url.path == "/internal/home":
            return httpx.Response(
                200,
                json={
                    "source": "reader",
                    "popular": [
                        summary("reader", f"popular-{index}", f"Popular {index}")
                        for index in range(5)
                    ],
                    "latest": [
                        summary("reader", f"latest-{index}", f"Latest {index}")
                        for index in range(5)
                    ],
                },
            )
        if request.url.path == "/internal/manga/import-summary":
            imported.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "manga"})
        raise AssertionError(f"unexpected request: {request.url}")

    scheduler = make_scheduler(monkeypatch, handler, catalogue_import_per_source_limit=2)
    try:
        await scheduler.import_catalogue(now=FIXED_NOW)
    finally:
        await close(scheduler)

    # The cap is shared: one title from each list is imported instead of the
    # whole popular list consuming the budget.
    assert [item["source_id"] for item in imported] == ["popular-0", "latest-0"]


@pytest.mark.asyncio
async def test_interval_gates_repeated_imports(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=[])

    scheduler = make_scheduler(
        monkeypatch,
        handler,
        catalogue_import_interval_seconds=3600,
    )
    try:
        assert scheduler.catalogue_import_due(FIXED_NOW) is True
        assert await scheduler.maybe_import_catalogue(FIXED_NOW) is True
        assert scheduler._last_catalogue_import == FIXED_NOW

        assert scheduler.catalogue_import_due(FIXED_NOW + timedelta(seconds=3599)) is False
        assert await scheduler.maybe_import_catalogue(FIXED_NOW + timedelta(seconds=3599)) is False
        assert len(calls) == 1

        assert scheduler.catalogue_import_due(FIXED_NOW + timedelta(seconds=3600)) is True
        assert await scheduler.maybe_import_catalogue(FIXED_NOW + timedelta(seconds=3600)) is True
        assert len(calls) == 2
        assert scheduler._last_catalogue_import == FIXED_NOW + timedelta(seconds=3600)
    finally:
        await close(scheduler)


@pytest.mark.asyncio
async def test_disabled_import_makes_no_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=[])

    scheduler = make_scheduler(monkeypatch, handler, catalogue_import_enabled=False)
    try:
        assert scheduler.catalogue_import_due(FIXED_NOW) is False
        assert await scheduler.maybe_import_catalogue(FIXED_NOW) is False
        await scheduler.import_catalogue(now=FIXED_NOW)
    finally:
        await close(scheduler)

    assert calls == []


@pytest.mark.asyncio
async def test_stub_summaries_are_enriched_after_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imported_details: list[dict[str, Any]] = []
    parser_requests: list[httpx.Request] = []
    stored = {
        "zero": stored_summary(
            "zero",
            chapters_count=0,
            description="Known metadata",
            genres=["Фэнтези"],
        ),
        "meta": stored_summary("meta", chapters_count=12, description=None, genres=[]),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/internal/sources":
            return httpx.Response(200, json=[source("reader")])
        if request.url.path == "/internal/home":
            return httpx.Response(
                200,
                json={
                    "source": "reader",
                    "popular": [
                        summary(
                            "reader",
                            "zero",
                            "Title zero",
                            url="https://reader.example/manga/zero",
                        ),
                        summary("reader", "meta", "Title meta"),
                    ],
                    "latest": [],
                },
            )
        if request.url.path == "/internal/manga/import-summary":
            payload = json.loads(request.content)
            return httpx.Response(200, json=stored[payload["source_id"]])
        if request.url.host == "parser.test" and request.url.path == "/internal/manga":
            parser_requests.append(request)
            return httpx.Response(
                200, json=parser_detail(request.url.params["source_id"], chapters=2)
            )
        if request.url.path == "/internal/manga/import-detail":
            imported_details.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "detail"})
        raise AssertionError(f"unexpected request: {request.url}")

    scheduler = make_scheduler(monkeypatch, handler)
    try:
        await scheduler.import_catalogue(now=FIXED_NOW)
    finally:
        await close(scheduler)

    assert {item["source_id"] for item in imported_details} == {"zero", "meta"}
    assert all(item["description"] for item in imported_details)
    assert all(item["genres"] == ["Фэнтези", "Приключения"] for item in imported_details)
    assert all(len(item["chapters"]) == 2 for item in imported_details)

    requests_by_id = {request.url.params["source_id"]: request for request in parser_requests}
    assert set(requests_by_id) == {"zero", "meta"}
    assert requests_by_id["zero"].url.params["source"] == "reader"
    assert requests_by_id["zero"].url.params["url"] == "https://reader.example/manga/zero"
    assert requests_by_id["zero"].url.params["chapters_limit"] == "1000"
    assert "url" not in requests_by_id["meta"].url.params


@pytest.mark.asyncio
async def test_complete_summaries_are_not_enriched_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser_requests: list[httpx.Request] = []
    imported_details: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/internal/sources":
            return httpx.Response(200, json=[source("reader")])
        if request.url.path == "/internal/home":
            return httpx.Response(
                200,
                json={
                    "source": "reader",
                    "popular": [summary("reader", "complete", "Complete title")],
                    "latest": [],
                },
            )
        if request.url.path == "/internal/manga/import-summary":
            return httpx.Response(
                200,
                json=stored_summary(
                    "complete",
                    chapters_count=42,
                    description="Complete description",
                    genres=["Фэнтези"],
                ),
            )
        if request.url.host == "parser.test" and request.url.path == "/internal/manga":
            parser_requests.append(request)
            return httpx.Response(200, json=parser_detail("complete"))
        if request.url.path == "/internal/manga/import-detail":
            imported_details.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "detail"})
        raise AssertionError(f"unexpected request: {request.url}")

    scheduler = make_scheduler(monkeypatch, handler)
    try:
        await scheduler.import_catalogue(now=FIXED_NOW)
    finally:
        await close(scheduler)

    assert parser_requests == []
    assert imported_details == []


@pytest.mark.asyncio
async def test_enrichment_failure_does_not_abort_other_titles(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    imported_details: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/internal/sources":
            return httpx.Response(200, json=[source("reader")])
        if request.url.path == "/internal/home":
            return httpx.Response(
                200,
                json={
                    "source": "reader",
                    "popular": [
                        summary("reader", "bad", "Broken enrichment"),
                        summary("reader", "good", "Healthy enrichment"),
                    ],
                    "latest": [],
                },
            )
        if request.url.path == "/internal/manga/import-summary":
            payload = json.loads(request.content)
            return httpx.Response(200, json=stored_summary(payload["source_id"]))
        if request.url.host == "parser.test" and request.url.path == "/internal/manga":
            source_id = request.url.params["source_id"]
            if source_id == "bad":
                return httpx.Response(500, json={"detail": "parser failure"})
            return httpx.Response(200, json=parser_detail(source_id))
        if request.url.path == "/internal/manga/import-detail":
            imported_details.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "detail"})
        raise AssertionError(f"unexpected request: {request.url}")

    scheduler = make_scheduler(monkeypatch, handler)
    try:
        with caplog.at_level(logging.INFO, logger="scheduler"):
            await scheduler.import_catalogue(now=FIXED_NOW)
    finally:
        await close(scheduler)

    assert [item["source_id"] for item in imported_details] == ["good"]
    assert "catalogue enrichment: reader/bad failed" in caplog.text
    assert "catalogue enrichment finished: candidates=2 enriched=1 failed=1" in caplog.text


@pytest.mark.asyncio
async def test_enrichment_cap_is_respected(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    parser_requests: list[httpx.Request] = []
    imported_details: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/internal/sources":
            return httpx.Response(200, json=[source("reader")])
        if request.url.path == "/internal/home":
            return httpx.Response(
                200,
                json={
                    "source": "reader",
                    "popular": [
                        summary("reader", f"stub-{index}", f"Stub {index}") for index in range(5)
                    ],
                    "latest": [],
                },
            )
        if request.url.path == "/internal/manga/import-summary":
            payload = json.loads(request.content)
            return httpx.Response(200, json=stored_summary(payload["source_id"]))
        if request.url.host == "parser.test" and request.url.path == "/internal/manga":
            parser_requests.append(request)
            return httpx.Response(200, json=parser_detail(request.url.params["source_id"]))
        if request.url.path == "/internal/manga/import-detail":
            imported_details.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "detail"})
        raise AssertionError(f"unexpected request: {request.url}")

    scheduler = make_scheduler(monkeypatch, handler, catalogue_enrichment_limit=2)
    try:
        with caplog.at_level(logging.INFO, logger="scheduler"):
            await scheduler.import_catalogue(now=FIXED_NOW)
    finally:
        await close(scheduler)

    assert len(parser_requests) == 2
    assert len(imported_details) == 2
    assert (
        "enrichment_candidates=2 enriched=2 enrichment_failed=0 enrichment_deferred=3"
        in caplog.text
    )


def test_defaults_are_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in (
        "CATALOGUE_IMPORT_ENABLED",
        "CATALOGUE_IMPORT_INTERVAL_SECONDS",
        "CATALOGUE_IMPORT_PER_SOURCE_LIMIT",
        "CATALOGUE_ENRICHMENT_ENABLED",
        "CATALOGUE_ENRICHMENT_CONCURRENCY",
        "CATALOGUE_ENRICHMENT_LIMIT",
    ):
        monkeypatch.delenv(variable, raising=False)
    settings = SchedulerSettings(_env_file=None)
    assert settings.catalogue_import_enabled is True
    assert settings.catalogue_import_interval_seconds == 21600
    assert settings.catalogue_import_per_source_limit == 60
    assert settings.catalogue_enrichment_enabled is True
    assert settings.catalogue_enrichment_concurrency == 3
    assert settings.catalogue_enrichment_limit == 30
