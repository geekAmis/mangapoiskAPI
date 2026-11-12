from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from manga_common.errors import AppError, app_error_handler
from manga_common.security import require_internal_token
from services.media.app import api as media_api
from services.media.app.archive import ArchivePruneResult, ArchiveStats
from services.media.app.cache import CachePruneResult, MediaCacheStats


class FakeCache:
    max_bytes = 10 * 1024 * 1024 * 1024

    async def stats(self) -> MediaCacheStats:
        return MediaCacheStats(
            used_bytes=9 * 1024 * 1024 * 1024,
            cap_bytes=self.max_bytes,
            files=42,
            evictions=3,
            last_pruned_at=datetime(2026, 11, 12, 10, 0, tzinfo=UTC),
        )

    async def prune(self, *, dry_run: bool = False) -> CachePruneResult:
        return CachePruneResult(
            removed=2,
            freed_bytes=1000,
            used_bytes=5000,
            cap_bytes=self.max_bytes,
            dry_run=dry_run,
        )


class FakeArchives:
    max_bytes = 25 * 1024 * 1024 * 1024

    async def stats(self) -> ArchiveStats:
        return ArchiveStats(
            total=5,
            done=3,
            failed=1,
            pending=1,
            done_bytes=self.max_bytes,
            db_bytes=32768,
            evictions=4,
            last_pruned_at=datetime(2026, 11, 12, 11, 0, tzinfo=UTC),
        )

    async def prune(self, *, dry_run: bool = False) -> ArchivePruneResult:
        return ArchivePruneResult(
            removed=1,
            freed_bytes=2000,
            used_bytes=3000,
            cap_bytes=self.max_bytes,
            dry_run=dry_run,
        )


def _client() -> TestClient:
    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.include_router(media_api.router)
    app.dependency_overrides[media_api.get_cache] = lambda: FakeCache()
    app.dependency_overrides[media_api.get_archives] = lambda: FakeArchives()
    app.dependency_overrides[require_internal_token] = lambda: None
    return TestClient(app)


def test_media_stats_reports_caps_evictions_and_warnings() -> None:
    with _client() as client:
        response = client.get("/internal/stats")

    assert response.status_code == 200
    payload = response.json()
    image = payload["image_cache"]
    assert image["used_bytes"] == 9 * 1024 * 1024 * 1024
    assert image["cap_bytes"] == 10 * 1024 * 1024 * 1024
    assert image["files"] == 42
    assert image["evictions"] == 3
    assert image["usage_percent"] == 90.0
    assert image["level"] == "critical"

    archives = payload["archives"]
    assert archives["done"] == 3
    assert archives["failed"] == 1
    assert archives["pending"] == 1
    assert archives["done_bytes"] == 25 * 1024 * 1024 * 1024
    assert archives["cap_bytes"] == 25 * 1024 * 1024 * 1024
    assert archives["usage_percent"] == 100.0
    assert archives["level"] == "critical"
    assert archives["evictions"] == 4

    assert len(payload["warnings"]) == 2
    assert "Кэш изображений" in payload["warnings"][0]
    assert "Архив глав" in payload["warnings"][1]


def test_media_stats_requires_internal_token() -> None:
    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.include_router(media_api.router)
    app.dependency_overrides[media_api.get_cache] = lambda: FakeCache()
    app.dependency_overrides[media_api.get_archives] = lambda: FakeArchives()

    with TestClient(app) as client:
        response = client.get("/internal/stats")

    assert response.status_code == 401


def test_maintenance_prune_defaults_to_dry_run() -> None:
    with _client() as client:
        response = client.post("/internal/maintenance/prune")

    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is True
    assert payload["image_cache"]["removed"] == 2
    assert payload["image_cache"]["dry_run"] is True
    assert payload["archives"]["removed"] == 1
    assert payload["archives"]["dry_run"] is True


def test_maintenance_prune_requires_internal_token() -> None:
    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.include_router(media_api.router)
    app.dependency_overrides[media_api.get_cache] = lambda: FakeCache()
    app.dependency_overrides[media_api.get_archives] = lambda: FakeArchives()

    with TestClient(app) as client:
        response = client.post("/internal/maintenance/prune", params={"dry_run": "false"})

    assert response.status_code == 401
