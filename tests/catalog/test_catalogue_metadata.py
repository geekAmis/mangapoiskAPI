from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from manga_common.db import create_all, create_engine, create_session_factory
from manga_common.source_models import ChapterSummary, MangaDetail, MangaSummary
from services.catalog.app.config import CatalogSettings
from services.catalog.app.repository import DESCRIPTION_FALLBACK
from services.catalog.app.service import CatalogService

from tests.fixtures.sample import sample_manga


async def make_service(
    tmp_path: Path, name: str = "metadata.db"
) -> tuple[CatalogService, object]:
    db_path = tmp_path / name
    settings = CatalogSettings(
        service_name="catalog-test",
        catalog_database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
    )
    engine = create_engine(settings.catalog_dsn)
    await create_all(engine)
    service = CatalogService(settings, create_session_factory(engine), None)  # type: ignore[arg-type]
    return service, engine


def chapter(source: str, source_id: str, number: str, when: datetime) -> ChapterSummary:
    return ChapterSummary(
        source=source,
        source_id=f"{source_id}-{number}",
        manga_source_id=source_id,
        number=number,
        title=f"Глава {number}",
        published_at=when,
    )


def detail(
    *,
    source: str,
    source_id: str,
    title: str,
    description: str | None = None,
    genres: list[str] | None = None,
    rating: float | None = None,
    poster_url: str | None = None,
    chapters: int = 1,
    published_at: datetime | None = None,
) -> MangaDetail:
    when = published_at or datetime(2026, 1, 1, tzinfo=UTC)
    return MangaDetail(
        source=source,
        source_id=source_id,
        slug=source_id,
        title=title,
        description=description,
        rating=rating,
        poster_url=poster_url or f"https://cdn.example/{source_id}.jpg",
        genres=genres or [],
        chapters=[
            chapter(source, source_id, str(number), when + timedelta(days=number))
            for number in range(1, chapters + 1)
        ],
    )


def summary(
    *,
    source: str,
    source_id: str,
    title: str,
    description: str | None = None,
    genres: list[str] | None = None,
    rating: float | None = None,
    rating_count: int | None = None,
    poster_url: str | None = None,
    chapters_count: int | None = None,
) -> MangaSummary:
    return MangaSummary(
        source=source,
        source_id=source_id,
        slug=source_id,
        title=title,
        description=description,
        genres=genres or [],
        rating=rating,
        rating_count=rating_count,
        poster_url=poster_url,
        chapters_count=chapters_count,
    )


@pytest.mark.asyncio
async def test_metadata_merge_and_covers_across_variants(tmp_path: Path) -> None:
    service, engine = await make_service(tmp_path)
    first = await service.import_detail(
        detail(
            source="mangapoisk",
            source_id="group-a",
            title="Общий тайтл",
            description="Описание из MangaPoisk.",
            genres=["Фэнтези"],
            rating=7.0,
            poster_url="https://cdn.example/a.jpg",
            chapters=4,
        )
    )
    second = await service.import_detail(
        detail(
            source="mangalib",
            source_id="group-b",
            title="Общий тайтл (перезапуск)",
            genres=["Ужасы"],
            rating=9.0,
            poster_url="https://cdn.example/b.jpg",
            chapters=2,
        )
    )

    merged = await service.manga_detail(first.manga.id)
    assert merged.description == "Описание из MangaPoisk."
    assert merged.description_missing is False
    assert merged.description_fallback is None
    assert set(merged.genres) == {"Фэнтези", "Ужасы"}
    assert merged.genre_slugs == ["fantasy", "horror"]
    assert merged.poster_url == "https://cdn.example/b.jpg"
    assert len(merged.covers) == 2
    primary = [cover for cover in merged.covers if cover.is_primary]
    assert len(primary) == 1
    assert primary[0].source == "mangalib"
    assert primary[0].source_id == "group-b"
    assert primary[0].rating == 9.0
    assert primary[0].chapters_count == 2
    assert primary[0].updated_at is not None

    other = await service.manga_detail(second.manga.id)
    assert other.description == merged.description
    assert other.poster_url == merged.poster_url

    # One card per normalised group, while both variants remain accessible.
    listing = await service.list(include_empty=True)
    assert listing.total == 1
    variants = await service.variants(first.manga.id)
    assert {item.source_id for item in variants.items} == {"group-a", "group-b"}

    await engine.dispose()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_cover_primary_tiebreak_uses_chapters_then_freshness(tmp_path: Path) -> None:
    service, engine = await make_service(tmp_path, "covers.db")
    old = datetime(2026, 1, 1, tzinfo=UTC)
    for source_id, chapters, when in (
        ("tie-a", 5, old),
        ("tie-b", 7, old),
        ("tie-c", 7, old + timedelta(days=10)),
    ):
        await service.import_detail(
            detail(
                source="mangapoisk",
                source_id=source_id,
                title="Одинаковый тайтл",
                rating=9.0,
                poster_url=f"https://cdn.example/{source_id}.jpg",
                chapters=chapters,
                published_at=when,
            )
        )

    manga = await service.list(include_empty=True)
    assert manga.total == 1
    detail_out = await service.manga_detail(manga.items[0].id)
    primary = [cover for cover in detail_out.covers if cover.is_primary]
    assert len(primary) == 1
    # Equal rating/chapter count, newest last chapter wins.
    assert primary[0].source_id == "tie-c"
    assert detail_out.poster_url == "https://cdn.example/tie-c.jpg"
    await engine.dispose()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_genre_and_filter_and_genre_counts(tmp_path: Path) -> None:
    service, engine = await make_service(tmp_path, "genres.db")
    rows = [
        ("horror-fantasy", ["Ужасы", "Фэнтези", "Меха"]),
        ("fantasy", ["Фэнтези"]),
        ("horror", ["Ужасы"]),
        ("romance", ["Романтика"]),
    ]
    for source_id, genres in rows:
        await service.import_detail(
            detail(
                source="mangapoisk",
                source_id=source_id,
                title=f"Тайтл {source_id}",
                genres=genres,
                chapters=1,
            )
        )

    both = await service.list(genres=["horror", "fantasy"])
    assert both.total == 1
    assert both.items[0].source_id == "horror-fantasy"

    via_string = await service.list(genres=["horror", "fantasy", "mecha"])
    assert via_string.total == 1

    only_horror = await service.list(genre="Ужасы")
    assert only_horror.total == 2

    genre_list = await service.genres()
    by_slug = {item.slug: item for item in genre_list.items}
    assert by_slug["horror"].label == "Ужасы"
    assert by_slug["horror"].count == 2
    assert by_slug["fantasy"].count == 2
    assert by_slug["mecha"].count == 1
    assert by_slug["romance"].count == 1
    await engine.dispose()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_empty_titles_are_hidden_from_lists_but_detail_works(tmp_path: Path) -> None:
    service, engine = await make_service(tmp_path, "empty.db")
    stub = await service.import_summary(
        summary(
            source="mangapoisk",
            source_id="stub",
            title="Милый дом",
            chapters_count=0,
        )
    )
    known_but_unparsed = await service.import_summary(
        summary(
            source="mangalib",
            source_id="known",
            title="Известный тайтл",
            chapters_count=12,
        )
    )
    filled = [
        await service.import_detail(
            detail(
                source="mangapoisk",
                source_id=f"filled-{index}",
                title=f"Заполненный {index}",
                chapters=1,
            )
        )
        for index in range(3)
    ]

    default = await service.list()
    assert default.total == 3
    assert {item.source_id for item in default.items} == {"filled-0", "filled-1", "filled-2"}
    assert all(item.chapters_count > 0 for item in default.items)

    first_page = await service.list(page=1, limit=2)
    second_page = await service.list(page=2, limit=2)
    assert first_page.total == 3 and len(first_page.items) == 2
    assert first_page.has_next is True
    assert second_page.total == 3 and len(second_page.items) == 1
    assert second_page.has_next is False

    with_empty = await service.list(include_empty=True)
    assert with_empty.total == 5
    assert {"stub", "known"} <= {item.source_id for item in with_empty.items}

    search = await service.list(query="Милый")
    assert search.total == 0
    search_with_empty = await service.list(query="Милый", include_empty=True)
    assert search_with_empty.total == 1

    # A direct detail id stays available for the "Обновить" path and clearly
    # signals that no source supplied a description.
    stub_detail = await service.manga_detail(stub.id)
    assert stub_detail.title == "Милый дом"
    assert stub_detail.description_missing is True
    assert stub_detail.description_fallback == DESCRIPTION_FALLBACK
    assert stub_detail.chapters == []

    known_detail = await service.manga_detail(known_but_unparsed.id)
    assert known_detail.chapters == []
    assert known_detail.description_missing is True

    for item in filled:
        assert (await service.manga_detail(item.manga.id)).chapters_count == 1
    await engine.dispose()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_home_updates_are_ordered_by_latest_chapter(tmp_path: Path) -> None:
    service, engine = await make_service(tmp_path, "updates.db")
    base = datetime(2026, 5, 1, tzinfo=UTC)
    await service.import_detail(
        detail(
            source="mangapoisk",
            source_id="older",
            title="Старый тайтл",
            chapters=2,
            published_at=base,
        )
    )
    await service.import_detail(
        detail(
            source="mangalib",
            source_id="newer",
            title="Новый тайтл",
            chapters=3,
            published_at=base + timedelta(days=10),
        )
    )

    updates = await service.home_updates(limit=4)
    assert updates.total == 4
    assert all(item.manga_id and item.chapter_id for item in updates.items)
    assert [item.chapter_number for item in updates.items] == ["3", "2", "1", "2"]
    assert updates.items[0].manga_title == "Новый тайтл"
    assert updates.items[0].source == "mangalib"
    assert updates.items[0].poster_url is not None
    assert updates.items[0].published_at is not None
    assert updates.items[0].added_at is not None

    limited = await service.home_updates(limit=1)
    assert limited.total == 1
    assert limited.items[0].chapter_number == "3"
    await engine.dispose()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_crawl_state_is_persistent_and_resumable(tmp_path: Path) -> None:
    from services.catalog.app.schemas import CrawlStateIn

    service, engine = await make_service(tmp_path, "crawl.db")
    next_run = datetime(2026, 6, 1, tzinfo=UTC)
    saved = await service.save_crawl_state(
        CrawlStateIn(
            source="mangapoisk",
            mode="full",
            page=17,
            status="running",
            last_error="temporary timeout",
            next_run_at=next_run,
            total_pages=163,
            items_seen=640,
            items_imported=600,
        )
    )
    assert saved.page == 17
    assert saved.status == "running"
    assert saved.last_error == "temporary timeout"
    assert saved.next_run_at == next_run

    loaded = await service.crawl_state("mangapoisk", "full")
    assert loaded is not None
    assert loaded.page == 17
    assert loaded.total_pages == 163

    await service.save_crawl_state(
        CrawlStateIn(
            source="mangapoisk",
            mode="full",
            page=163,
            status="completed",
            total_pages=163,
            items_seen=6484,
            items_imported=6484,
        )
    )
    completed = await service.crawl_state("mangapoisk", "full")
    assert completed is not None and completed.status == "completed"
    assert completed.page == 163
    assert [state.mode for state in await service.crawl_states(source="mangapoisk")] == ["full"]
    await engine.dispose()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_import_summary_never_wipes_metadata_or_covers(tmp_path: Path) -> None:
    service, engine = await make_service(tmp_path, "preserve.db")
    imported = await service.import_detail(sample_manga())
    await service.import_summary(
        summary(
            source="mangapoisk",
            source_id="sample-manga",
            title="Пример манги",
            description=None,
            genres=[],
            poster_url="https://static2.mangapoisk.me/posters/2/cover.jpg",
        )
    )
    result = await service.manga_detail(imported.manga.id)
    assert result.description == "Описание тестовой манги."
    assert result.genres == ["фэнтези", "приключения"]
    assert len(result.covers) == 1
    assert result.covers[0].url == "https://static2.mangapoisk.me/posters/2/cover.jpg"
    await engine.dispose()  # type: ignore[attr-defined]
