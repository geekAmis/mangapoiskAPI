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


def summary(source_code: str | None, source_id: str, title: str) -> dict[str, Any]:
    item = {"source_id": source_id, "title": title}
    if source_code is not None:
        item["source"] = source_code
    return item


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


def test_defaults_are_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in (
        "CATALOGUE_IMPORT_ENABLED",
        "CATALOGUE_IMPORT_INTERVAL_SECONDS",
        "CATALOGUE_IMPORT_PER_SOURCE_LIMIT",
    ):
        monkeypatch.delenv(variable, raising=False)
    settings = SchedulerSettings(_env_file=None)
    assert settings.catalogue_import_enabled is True
    assert settings.catalogue_import_interval_seconds == 21600
    assert settings.catalogue_import_per_source_limit == 60
