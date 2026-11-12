from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from manga_common.errors import AppError, app_error_handler
from manga_common.security import require_admin
from services.gateway.app import api as gateway_api

PAYLOAD = {
    "generated_at": "2026-11-12T12:00:00Z",
    "image_cache": {
        "used_bytes": 100,
        "cap_bytes": 1000,
        "files": 2,
        "evictions": 1,
        "last_pruned_at": None,
        "usage_percent": 10.0,
        "level": "ok",
    },
    "archives": {
        "total": 1,
        "done": 1,
        "failed": 0,
        "pending": 0,
        "done_bytes": 50,
        "db_bytes": 10,
        "cap_bytes": 1000,
        "evictions": 0,
        "last_pruned_at": None,
        "usage_percent": 5.0,
        "level": "ok",
    },
    "warnings": [],
}


class FakeMedia:
    async def stats(self) -> dict[str, object]:
        return PAYLOAD


def _client() -> TestClient:
    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.state.catalog = None
    app.state.parser = None
    app.state.library = None
    app.state.media = FakeMedia()
    app.include_router(gateway_api.router)
    app.dependency_overrides[require_admin] = lambda: None
    return TestClient(app)


def test_admin_media_stats_proxies_media_payload() -> None:
    with _client() as client:
        response = client.get("/api/v1/admin/media/stats")

    assert response.status_code == 200
    assert response.json() == PAYLOAD


def test_admin_media_stats_requires_admin() -> None:
    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.state.media = FakeMedia()
    app.include_router(gateway_api.router)

    with TestClient(app) as client:
        response = client.get("/api/v1/admin/media/stats")

    assert response.status_code == 401
