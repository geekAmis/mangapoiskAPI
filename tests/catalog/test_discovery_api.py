from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from manga_common.db import create_all, create_engine, create_session_factory
from manga_common.errors import AppError, app_error_handler
from manga_common.security import require_internal_token
from manga_common.source_models import ChapterSummary, MangaDetail
from services.catalog.app.api import get_service, router
from services.catalog.app.config import CatalogSettings
from services.catalog.app.discovery import seed_smart_collections
from services.catalog.app.service import CatalogService


def detail(
    source_id: str,
    *,
    title: str,
    genres: list[str],
    chapters: int = 12,
    rating: float = 7.5,
    status: str = "Выходит",
    days_ago: int = 1,
) -> MangaDetail:
    now = datetime.now(UTC) - timedelta(days=days_ago)
    return MangaDetail(
        source="test",
        source_id=source_id,
        slug=source_id,
        title=title,
        year=2024,
        status=status,
        content_type="Манга",
        rating=rating,
        rating_count=100,
        genres=genres,
        poster_url=f"https://cdn.example/{source_id}.jpg",
        chapters=[
            ChapterSummary(
                source="test",
                source_id=f"{source_id}-{index}",
                manga_source_id=source_id,
                number=str(index),
                title=f"Глава {index}",
                published_at=now,
            )
            for index in range(1, chapters + 1)
        ],
    )


@pytest.fixture
async def api(tmp_path: Path):
    db_path = tmp_path / "discovery-api.db"
    settings = CatalogSettings(
        service_name="catalog-discovery-api-test",
        catalog_database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
    )
    engine = create_engine(settings.catalog_dsn)
    await create_all(engine)
    session_factory = create_session_factory(engine)
    async with session_factory() as session:
        await seed_smart_collections(session)
        await session.commit()
    service = CatalogService(settings, session_factory, None)  # type: ignore[arg-type]
    for index in range(10):
        await service.import_detail(
            detail(
                f"api-{index}",
                title=f"Тайтл API {index}",
                genres=["Фэнтези", "Боевик"],
                chapters=60 if index < 6 else 20,
                rating=7.0 + index * 0.2,
                status="Завершено" if index < 4 else "Выходит",
                days_ago=index,
            )
        )
    await service.import_detail(
        detail("api-stub", title="Пустая заглушка", genres=["Фэнтези"], chapters=0)
    )

    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.include_router(router)
    app.dependency_overrides[require_internal_token] = lambda: None
    app.dependency_overrides[get_service] = lambda: service
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, service
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_public_collections_endpoint_is_ordered_and_clean(api) -> None:
    client, _ = api
    response = await client.get("/internal/collections", params={"limit": 6})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == len(payload["items"])
    slugs = [item["slug"] for item in payload["items"]]
    assert slugs[:5] == ["weekly-best", "beginners", "completed", "short", "new"]
    for collection in payload["items"]:
        assert collection["enabled"] is True
        assert collection["items"]
        ids = [item["id"] for item in collection["items"]]
        assert len(ids) == len(set(ids))
        assert all(item["chapters_count"] > 0 for item in collection["items"])
        assert all((item["poster_url"] or "").strip() for item in collection["items"])
        assert all(item["title"] != "Пустая заглушка" for item in collection["items"])
    completed = next(item for item in payload["items"] if item["slug"] == "completed")
    assert all(item["status"] == "Завершено" for item in completed["items"])


@pytest.mark.asyncio
async def test_related_endpoint_accepts_history_and_returns_similar(api) -> None:
    client, service = api
    seed = await service.import_detail(
        detail(
            "api-seed",
            title="Сид похожего",
            genres=["Фэнтези", "Боевик"],
            chapters=100,
            rating=8.9,
        )
    )
    read = await service.import_detail(
        detail(
            "api-read",
            title="Прочитанное похожее",
            genres=["Фэнтези", "Боевик"],
            chapters=90,
            rating=8.8,
        )
    )
    response = await client.get(
        f"/internal/manga/{seed.manga.id}/related",
        params={"history": str(read.manga.id), "limit": 6},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["similar"]
    assert len(payload["similar"]) == 6
    ids = [item["id"] for item in payload["similar"]]
    assert str(seed.manga.id) not in ids
    assert str(read.manga.id) not in ids


@pytest.mark.asyncio
async def test_admin_collection_api_crud_order_and_audit(api) -> None:
    client, service = api
    first = await service.import_detail(
        detail("api-manual-1", title="Первый ручной", genres=["Драма"])
    )
    second = await service.import_detail(
        detail("api-manual-2", title="Второй ручной", genres=["Драма"])
    )

    created = await client.post(
        "/internal/admin/collections",
        json={"title": "API подборка", "kind": "manual", "limit": 6},
    )
    assert created.status_code == 200
    collection = created.json()
    collection_id = collection["id"]
    assert collection["slug"] == "api-podborka"

    added = await client.post(
        f"/internal/admin/collections/{collection_id}/items",
        json={"manga_id": str(first.manga.id)},
    )
    assert added.status_code == 200
    added = await client.post(
        f"/internal/admin/collections/{collection_id}/items",
        json={"manga_id": str(second.manga.id)},
    )
    assert [item["id"] for item in added.json()["items"]] == [
        str(first.manga.id),
        str(second.manga.id),
    ]

    reordered = await client.put(
        f"/internal/admin/collections/{collection_id}/order",
        json={"manga_ids": [str(second.manga.id), str(first.manga.id)]},
    )
    assert [item["id"] for item in reordered.json()["items"]] == [
        str(second.manga.id),
        str(first.manga.id),
    ]

    public = await client.get(f"/internal/collections/{collection['slug']}")
    assert [item["id"] for item in public.json()["items"]] == [
        str(second.manga.id),
        str(first.manga.id),
    ]

    updated = await client.patch(
        f"/internal/admin/collections/{collection_id}",
        json={"title": "API подборка 2", "enabled": False},
    )
    assert updated.status_code == 200
    assert updated.json()["enabled"] is False
    assert (await client.get(f"/internal/collections/{collection['slug']}")).status_code == 404

    audit = await client.get("/internal/admin/collections/audit", params={"limit": 20})
    assert audit.status_code == 200
    actions = {item["action"] for item in audit.json()}
    assert {
        "collection.created",
        "collection.item_added",
        "collection.reordered",
        "collection.updated",
    } <= actions
    assert all("password" not in str(item["details"]).lower() for item in audit.json())

    deleted = await client.delete(f"/internal/admin/collections/{collection_id}")
    assert deleted.status_code == 200
    assert (await client.get(f"/internal/collections/{collection['slug']}")).status_code == 404
