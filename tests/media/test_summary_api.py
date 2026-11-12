from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from manga_common.config import Settings, get_settings
from manga_common.errors import AppError, app_error_handler
from manga_common.security import require_internal_token
from services.media.app import api as media_api
from services.media.app.archive import ArchiveSummaryItem

DONE_ID = uuid.uuid4()
MISSING_ID = uuid.uuid4()


class FakeArchives:
    async def summary(self, chapter_ids: list[uuid.UUID]) -> list[ArchiveSummaryItem]:
        return [
            ArchiveSummaryItem(chapter_id=chapter_id, status="done", page_count=4)
            if chapter_id == DONE_ID
            else ArchiveSummaryItem(chapter_id=chapter_id, status="missing")
            for chapter_id in chapter_ids
        ]


def _client() -> TestClient:
    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.include_router(media_api.router)
    app.dependency_overrides[media_api.get_archives] = lambda: FakeArchives()
    app.dependency_overrides[require_internal_token] = lambda: None
    return TestClient(app)


def test_summary_endpoint_is_not_shadowed_by_chapter_status_route() -> None:
    with _client() as client:
        response = client.get(
            "/internal/archives/chapters/summary",
            params={"ids": f"{MISSING_ID},{DONE_ID}"},
        )

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["chapter_id"] for item in items] == [str(MISSING_ID), str(DONE_ID)]
    assert items[0]["status"] == "missing"
    assert items[1]["status"] == "done"
    assert items[1]["page_count"] == 4


def test_summary_endpoint_requires_internal_token() -> None:
    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.include_router(media_api.router)
    app.dependency_overrides[media_api.get_archives] = lambda: FakeArchives()
    app.dependency_overrides[get_settings] = lambda: Settings(internal_token="summary-test-token")

    with TestClient(app) as client:
        missing = client.get(
            "/internal/archives/chapters/summary",
            params={"ids": str(DONE_ID)},
        )
        allowed = client.get(
            "/internal/archives/chapters/summary",
            params={"ids": str(DONE_ID)},
            headers={"X-Internal-Token": "summary-test-token"},
        )

    assert missing.status_code == 401
    assert allowed.status_code == 200
    assert allowed.json()["items"][0]["status"] == "done"


def test_summary_endpoint_rejects_invalid_ids() -> None:
    with _client() as client:
        response = client.get(
            "/internal/archives/chapters/summary",
            params={"ids": "not-a-uuid"},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
