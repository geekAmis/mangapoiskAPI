from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from manga_common.db import create_all, create_engine, create_session_factory
from manga_common.errors import NotFoundError, ValidationError
from manga_common.source_models import ChapterSummary, MangaDetail
from services.catalog.app.config import CatalogSettings
from services.catalog.app.discovery import seed_smart_collections
from services.catalog.app.models import MangaCollectionItem
from services.catalog.app.recommendations import clear_discovery_cache
from services.catalog.app.schemas import (
    CollectionCreate,
    CollectionItemIn,
    CollectionOrderIn,
    CollectionUpdate,
)
from services.catalog.app.service import CatalogService
from sqlalchemy import func, select


def detail(
    source_id: str,
    *,
    title: str,
    genres: list[str],
    chapters: int = 12,
    rating: float | None = 7.5,
    rating_count: int = 100,
    year: int | None = 2024,
    status: str | None = "Выходит",
    content_type: str | None = "Манга",
    days_ago: int = 2,
    poster: bool = True,
) -> MangaDetail:
    now = datetime.now(UTC) - timedelta(days=days_ago)
    return MangaDetail(
        source="test",
        source_id=source_id,
        slug=source_id,
        title=title,
        year=year,
        status=status,
        content_type=content_type,
        rating=rating,
        rating_count=rating_count,
        genres=genres,
        poster_url=f"https://cdn.example/{source_id}.jpg" if poster else None,
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
async def catalog(tmp_path: Path):
    db_path = tmp_path / "discovery.db"
    settings = CatalogSettings(
        service_name="catalog-discovery-test",
        catalog_database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
    )
    engine = create_engine(settings.catalog_dsn)
    await create_all(engine)
    session_factory = create_session_factory(engine)
    async with session_factory() as session:
        await seed_smart_collections(session)
        await session.commit()
    service = CatalogService(settings, session_factory, None)  # type: ignore[arg-type]
    clear_discovery_cache()
    try:
        yield service
    finally:
        await engine.dispose()
        clear_discovery_cache()


@pytest.mark.asyncio
async def test_similar_is_relevant_clean_and_excludes_read(catalog: CatalogService) -> None:
    seed = await catalog.import_detail(
        detail(
            "seed",
            title="Клинок рассвета",
            genres=["Фэнтези", "Боевик"],
            chapters=100,
            rating=8.8,
            year=2024,
            content_type="Манга",
        )
    )
    relevant: list[uuid.UUID] = []
    for index in range(8):
        row = await catalog.import_detail(
            detail(
                f"relevant-{index}",
                title=f"Похожий кандидат {index}",
                genres=["Фэнтези", "Боевик"] if index % 2 == 0 else ["Фэнтези", "Приключения"],
                chapters=80 + index * 5,
                rating=8.0 + index * 0.1,
                year=2022 + index % 3,
                content_type="Манга",
                days_ago=index + 1,
            )
        )
        relevant.append(row.manga.id)
    for index in range(8):
        await catalog.import_detail(
            detail(
                f"irrelevant-{index}",
                title=f"Далекий кандидат {index}",
                genres=["Романтика", "Комедия"],
                chapters=4 + index,
                rating=5.0 + index * 0.2,
                year=2003 + index,
                content_type="Манхва",
                days_ago=200,
            )
        )
    await catalog.import_detail(
        detail("stub", title="Пустая заглушка", genres=["Фэнтези"], chapters=0)
    )
    await catalog.import_detail(
        detail(
            "seed-variant",
            title="Клинок рассвета",
            genres=["Фэнтези", "Боевик"],
            chapters=90,
            rating=8.7,
        )
    )
    read_id = relevant[0]

    result = await catalog.related(seed.manga.id, history_ids=[read_id], limit=12)
    ids = [item.id for item in result.similar]
    assert 6 <= len(ids) <= 12
    assert len(ids) == len(set(ids))
    assert seed.manga.id not in ids
    assert read_id not in ids
    assert all(item.chapters_count > 0 for item in result.similar)
    assert all((item.poster_url or "").strip() for item in result.similar)
    # The closest titles are fantasy/action, not the intentionally distant set.
    assert sum(
        1
        for item in result.similar
        if {"fantasy", "action"} & set(item.genre_slugs or [])
    ) >= 6
    # Another source variant of the same title group must never appear.
    assert not any(item.title == "Клинок рассвета" for item in result.similar)

    without_history = await catalog.related(seed.manga.id, limit=6)
    assert len(without_history.similar) == 6
    assert len({item.id for item in without_history.similar}) == 6


@pytest.mark.asyncio
async def test_smart_collections_are_deterministic_and_clean(catalog: CatalogService) -> None:
    for index in range(10):
        status = "Завершено" if index < 6 else "Выходит"
        chapters = 8 + index * 10 if index < 6 else 60 + index
        await catalog.import_detail(
            detail(
                f"smart-{index}",
                title=f"Подборка {index}",
                genres=["Фэнтези", "Приключения"],
                chapters=chapters,
                rating=7.0 + index * 0.2,
                rating_count=100 + index * 10,
                status=status,
                days_ago=index,
            )
        )
    await catalog.import_detail(
        detail("smart-stub", title="Пустая заглушка", genres=["Фэнтези"], chapters=0)
    )

    first = await catalog.collections(limit=8)
    slugs = [item.slug for item in first.items]
    assert slugs[:5] == ["weekly-best", "beginners", "completed", "short", "new"]
    assert all(item.items for item in first.items)
    for collection in first.items:
        ids = [item.id for item in collection.items]
        assert len(ids) == len(set(ids))
        assert all(item.chapters_count > 0 for item in collection.items)
        assert all((item.poster_url or "").strip() for item in collection.items)
        assert all(item.title != "Пустая заглушка" for item in collection.items)
    completed = next(item for item in first.items if item.slug == "completed")
    assert all(item.status == "Завершено" for item in completed.items)
    short = next(item for item in first.items if item.slug == "short")
    assert all(item.chapters_count <= 30 for item in short.items)

    clear_discovery_cache()
    second = await catalog.collections(limit=8)
    assert [[item.id for item in shelf.items] for shelf in second.items] == [
        [item.id for item in shelf.items] for shelf in first.items
    ]


@pytest.mark.asyncio
async def test_admin_collection_crud_order_and_audit(catalog: CatalogService) -> None:
    first = await catalog.import_detail(
        detail("manual-1", title="Первый тайтл", genres=["Драма"])
    )
    second = await catalog.import_detail(
        detail("manual-2", title="Второй тайтл", genres=["Драма"])
    )
    stub = await catalog.import_detail(
        detail("manual-stub", title="Заглушка", genres=["Драма"], chapters=0)
    )

    created = await catalog.create_collection(
        CollectionCreate(
            title="Ручная подборка",
            description="Выбор редакции",
            kind="manual",
            position=5,
            limit=6,
        )
    )
    assert created.kind == "manual"
    assert created.slug == "ruchnaya-podborka"

    with pytest.raises(ValidationError):
        await catalog.add_collection_item(created.id, CollectionItemIn(manga_id=stub.manga.id))

    await catalog.add_collection_item(created.id, CollectionItemIn(manga_id=first.manga.id))
    updated = await catalog.add_collection_item(
        created.id, CollectionItemIn(manga_id=second.manga.id)
    )
    assert [item.id for item in updated.items] == [first.manga.id, second.manga.id]

    reordered = await catalog.reorder_collection_items(
        created.id, CollectionOrderIn(manga_ids=[second.manga.id, first.manga.id])
    )
    assert [item.id for item in reordered.items] == [second.manga.id, first.manga.id]

    public = await catalog.collection(created.slug, limit=24)
    assert [item.id for item in public.items] == [second.manga.id, first.manga.id]

    renamed = await catalog.update_collection(
        created.id,
        CollectionUpdate(title="Обновлённая подборка", description="Новое описание", enabled=True),
    )
    assert renamed.title == "Обновлённая подборка"
    assert renamed.description == "Новое описание"

    after_remove = await catalog.remove_collection_item(created.id, first.manga.id)
    assert [item.id for item in after_remove.items] == [second.manga.id]

    audit = await catalog.collection_audit(limit=50)
    actions = {item.action for item in audit}
    assert {
        "collection.created",
        "collection.item_added",
        "collection.reordered",
        "collection.updated",
        "collection.item_removed",
    } <= actions
    assert all("password" not in str(item.details).lower() for item in audit)

    await catalog.delete_collection(created.id)
    with pytest.raises(NotFoundError):
        await catalog.collection(created.slug, limit=24)


@pytest.mark.asyncio
async def test_import_invalidates_collection_cache(catalog: CatalogService) -> None:
    for index in range(3):
        await catalog.import_detail(
            detail(
                f"cache-{index}",
                title=f"Старый тайтл {index}",
                genres=["Драма"],
                chapters=20,
                rating=7.0 + index * 0.2,
                status="Завершено",
            )
        )
    before = await catalog.collections(limit=12)
    completed_before = next(item for item in before.items if item.slug == "completed")
    assert len(completed_before.items) == 3

    fresh = await catalog.import_detail(
        detail(
            "cache-new",
            title="Свежий завершённый тайтл",
            genres=["Драма"],
            chapters=40,
            rating=9.9,
            rating_count=10_000,
            status="Завершено",
        )
    )
    after = await catalog.collections(limit=12)
    completed_after = next(item for item in after.items if item.slug == "completed")
    assert fresh.manga.id in [item.id for item in completed_after.items]


@pytest.mark.asyncio
async def test_rule_shelves_never_mix_in_wrong_status(catalog: CatalogService) -> None:
    # No completed and no short titles: those sections must be omitted instead
    # of being back-filled with unrelated ongoing/long titles.
    for index in range(8):
        await catalog.import_detail(
            detail(
                f"ongoing-{index}",
                title=f"Онгоинг {index}",
                genres=["Фэнтези", "Боевик"],
                chapters=60 + index,
                rating=7.5 + index * 0.1,
                status="Выходит",
            )
        )

    shelves = await catalog.collections(limit=12)
    slugs = [item.slug for item in shelves.items]
    assert "completed" not in slugs
    assert "short" not in slugs
    assert "weekly-best" in slugs
    assert "beginners" in slugs
    assert "new" in slugs
    for shelf in shelves.items:
        assert shelf.items
        assert len({item.id for item in shelf.items}) == len(shelf.items)


@pytest.mark.asyncio
async def test_disabled_collection_is_hidden_from_public_api(catalog: CatalogService) -> None:
    manga = await catalog.import_detail(
        detail("hidden-1", title="Скрытый тайтл", genres=["Драма"])
    )
    created = await catalog.create_collection(
        CollectionCreate(title="Скрытая подборка", kind="manual")
    )
    await catalog.add_collection_item(created.id, CollectionItemIn(manga_id=manga.manga.id))
    assert (await catalog.collection(created.slug)).items

    await catalog.update_collection(created.id, CollectionUpdate(enabled=False))
    public = await catalog.collections(limit=24)
    assert created.slug not in [item.slug for item in public.items]
    with pytest.raises(NotFoundError):
        await catalog.collection(created.slug)

    admin = await catalog.admin_collections()
    hidden = next(item for item in admin.items if item.slug == created.slug)
    assert hidden.enabled is False
    assert [item.id for item in hidden.items] == [manga.manga.id]


@pytest.mark.asyncio
async def test_similar_cache_is_invalidated_on_import(catalog: CatalogService) -> None:
    seed = await catalog.import_detail(
        detail(
            "similar-cache-seed",
            title="Кэш-сид",
            genres=["Фэнтези", "Боевик"],
            chapters=100,
            rating=9.0,
        )
    )
    for index in range(6):
        await catalog.import_detail(
            detail(
                f"similar-cache-old-{index}",
                title=f"Старый похожий {index}",
                genres=["Фэнтези", "Боевик"],
                chapters=90,
                rating=7.0 + index * 0.1,
            )
        )
    before = await catalog.similar(seed.manga.id, limit=12)
    assert len(before) == 6
    assert seed.manga.id not in [item.id for item in before]

    fresh = await catalog.import_detail(
        detail(
            "similar-cache-new",
            title="Новый похожий",
            genres=["Фэнтези", "Боевик"],
            chapters=100,
            rating=9.8,
            rating_count=50_000,
        )
    )
    after = await catalog.similar(seed.manga.id, limit=12)
    assert fresh.manga.id in [item.id for item in after]
    assert seed.manga.id not in [item.id for item in after]


@pytest.mark.asyncio
async def test_manual_collection_respects_preview_limit_and_cleans_items(
    catalog: CatalogService,
) -> None:
    titles = []
    for index in range(4):
        result = await catalog.import_detail(
            detail(f"preview-{index}", title=f"Превью {index}", genres=["Драма"])
        )
        titles.append(result.manga.id)

    created = await catalog.create_collection(
        CollectionCreate(title="Превью-подборка", kind="manual", limit=3)
    )
    for manga_id in titles:
        await catalog.add_collection_item(created.id, CollectionItemIn(manga_id=manga_id))

    public = await catalog.collections(limit=12)
    shelf = next(item for item in public.items if item.slug == created.slug)
    assert len(shelf.items) == 3
    assert [item.id for item in shelf.items] == titles[:3]

    await catalog.delete_collection(created.id)


    async with catalog.session_factory() as session:
        remaining = await session.scalar(select(func.count()).select_from(MangaCollectionItem))
    assert remaining == 0


@pytest.mark.asyncio
async def test_deleted_smart_collection_is_not_resurrected(catalog: CatalogService) -> None:
    admin = await catalog.admin_collections()
    weekly = next(item for item in admin.items if item.slug == "weekly-best")
    await catalog.delete_collection(weekly.id)

    public = await catalog.collections(limit=12)
    assert "weekly-best" not in [item.slug for item in public.items]
    admin_after = await catalog.admin_collections()
    assert "weekly-best" not in [item.slug for item in admin_after.items]
    with pytest.raises(NotFoundError):
        await catalog.collection("weekly-best")

    # A restart must not re-seed a table that already has editorial rows.
    async with catalog.session_factory() as session:
        assert await seed_smart_collections(session) == 0
        await session.commit()
