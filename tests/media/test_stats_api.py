from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from manga_common.errors import AppError, app_error_handler
from manga_common.security import require_internal_token
from services.media.app import api as media_api
from services.media.app.archive import ArchiveStats
from services.media.app.cache import MediaCacheStats


class FakeCache:
    async def stats(self) -> MediaCacheStats:
        return MediaCacheStats(bytes=1_500_000, files=17)


class FakeArchives:
    max_bytes = 25 * 1024 * 1024 * 1024

    async def stats(self) -> ArchiveStats:
        return ArchiveStats(
            total=3,
            done=2,
            failed=1,
            pending=0,
            done_bytes=1_000_000,
            db_bytes=32_768,
        )


def _client() -> TestClient:
    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.include_router(media_api.router)
    app.dependency_overrides[media_api.get_cache] = lambda: FakeCache()
    app.dependency_overrides[media_api.get_archives] = lambda: FakeArchives()
    app.dependency_overrides[require_internal_token] = lambda: None
    return TestClient(app)


def test_media_stats_reports_archive_and_cache_usage() -> None:
    with _client() as client:
        response = client.get("/internal/stats")

    assert response.status_code == 200
    payload = response.json()
    assert payload["archives"]["done"] == 2
    assert payload["archives"]["failed"] == 1
    assert payload["archives"]["done_bytes"] == 1_000_000
    assert payload["archives"]["cap_bytes"] == 25 * 1024 * 1024 * 1024
    assert payload["archives"]["usage_percent"] == 0.0
    assert payload["image_cache_bytes"] == 1_500_000
    assert payload["image_cache_files"] == 17


def test_media_stats_requires_internal_token() -> None:
    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.include_router(media_api.router)
    app.dependency_overrides[media_api.get_cache] = lambda: FakeCache()
    app.dependency_overrides[media_api.get_archives] = lambda: FakeArchives()

    with TestClient(app) as client:
        response = client.get("/internal/stats")

    assert response.status_code == 401
