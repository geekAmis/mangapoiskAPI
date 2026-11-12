from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from manga_common.errors import AppError, app_error_handler
from manga_common.schemas import (
    CollectionAuditOut,
    CollectionListOut,
    CollectionOut,
    RelatedMangaOut,
)
from manga_common.security import require_admin
from services.gateway.app.retention import router

MANGA = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
READ = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


class FakeCatalog:
    def __init__(self) -> None:
        self.related_calls: list[tuple[str, list[str], int]] = []
        self.created: list[dict] = []
        self.deleted: list[str] = []

    async def related(self, manga_id: str, *, history_ids=None, limit=12) -> RelatedMangaOut:
        self.related_calls.append((manga_id, list(history_ids or []), limit))
        return RelatedMangaOut()

    async def collections(self, *, limit: int = 12) -> CollectionListOut:
        return CollectionListOut()

    async def collection(self, slug: str, *, limit: int = 24) -> CollectionOut:
        return CollectionOut(
            id=uuid.uuid4(),
            slug=slug,
            title=slug,
            description="",
            kind="manual",
            items=[],
        )

    async def admin_collections(self) -> CollectionListOut:
        return CollectionListOut()

    async def create_collection(self, payload: dict) -> CollectionOut:
        self.created.append(payload)
        return CollectionOut(
            id=uuid.uuid4(),
            slug="new-shelf",
            title=str(payload.get("title", "")),
            description="",
            kind="manual",
            items=[],
        )

    async def collection_audit(self, limit: int = 100) -> list[CollectionAuditOut]:
        return []

    async def delete_collection(self, collection_id: str) -> None:
        self.deleted.append(collection_id)


class FakeLibrary:
    async def analytics_surfaces(self, days: int):
        return {"days": days, "generated_at": "2026-11-13T00:00:00Z", "items": []}


def make_client(*, admin: bool = False) -> tuple[TestClient, FakeCatalog]:
    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    catalog = FakeCatalog()
    app.state.catalog = catalog
    app.state.library = FakeLibrary()
    app.include_router(router)
    if admin:
        app.dependency_overrides[require_admin] = lambda: None
    return TestClient(app), catalog


def test_related_forwards_local_history_and_is_cacheable() -> None:
    client, catalog = make_client()
    with client as http:
        response = http.get(
            f"/api/v1/manga/{MANGA}/related",
            params={"history": READ, "limit": 6},
        )
    assert response.status_code == 200
    assert catalog.related_calls == [(MANGA, [READ], 6)]
    assert response.headers["cache-control"] == "public, max-age=120"


def test_related_rejects_history_over_the_supported_length() -> None:
    client, _ = make_client()
    with client as http:
        response = http.get(
            f"/api/v1/manga/{MANGA}/related",
            params={"history": "x" * 4097},
        )
    assert response.status_code == 422


def test_admin_collection_routes_require_admin_and_forward_payloads() -> None:
    client, _ = make_client()
    with client as http:
        assert http.get("/api/v1/admin/collections").status_code == 401

    client, catalog = make_client(admin=True)
    with client as http:
        created = http.post(
            "/api/v1/admin/collections",
            json={"title": "Редакционная", "kind": "manual"},
        )
        assert created.status_code == 200
        assert catalog.created[0]["title"] == "Редакционная"

        listed = http.get("/api/v1/admin/collections")
        assert listed.status_code == 200

        audit = http.get("/api/v1/admin/collections/audit")
        assert audit.status_code == 200

        deleted = http.delete(f"/api/v1/admin/collections/{uuid.uuid4()}")
        assert deleted.status_code == 200
