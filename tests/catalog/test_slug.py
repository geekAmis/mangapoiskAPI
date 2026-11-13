from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from manga_common.db import create_all, create_engine, create_session_factory
from manga_common.source_models import ChapterSummary, MangaDetail
from manga_common.text import build_url_slug
from services.catalog.app.config import CatalogSettings
from services.catalog.app.migrations import ensure_runtime_schema
from services.catalog.app.models import Manga
from services.catalog.app.repository import backfill_url_slugs
from services.catalog.app.service import CatalogService
from services.catalog.app.slug_backfill import run_slug_backfill
from sqlalchemy import select, text


def detail(
    source_id: str,
    *,
    title: str,
    adult: bool = False,
    chapters: int = 1,
) -> MangaDetail:
    return MangaDetail(
        source="mangapoisk",
        source_id=source_id,
        slug=source_id,
        title=title,
        description=f"Описание {title}",
        poster_url=f"https://cdn.example/{source_id}.jpg",
        adult=adult,
        genres=["Экшен"],
        chapters=[
            ChapterSummary(
                source="mangapoisk",
                source_id=f"{source_id}-{index}",
                manga_source_id=source_id,
                number=str(index),
                title=f"Глава {index}",
                published_at=datetime(2026, 5, 1, tzinfo=UTC),
            )
            for index in range(1, chapters + 1)
        ],
    )


@pytest.fixture
async def service(tmp_path: Path):
    settings = CatalogSettings(
        service_name="catalog-slug-test",
        catalog_database_url=f"sqlite+aiosqlite:///{(tmp_path / 'slug.db').as_posix()}",
    )
    engine = create_engine(settings.catalog_dsn)
    await create_all(engine)
    session_factory = create_session_factory(engine)
    yield CatalogService(settings, session_factory, None), session_factory  # type: ignore[arg-type]
    await engine.dispose()


def test_build_url_slug_transliterates_and_is_bounded() -> None:
    assert build_url_slug("Ванпанчмен") == "vanpanchmen"
    assert build_url_slug("Человек-бензопила") == "chelovek-benzopila"
    assert build_url_slug("Re:Zero — жизнь в другом мире") == "re-zero-zhizn-v-drugom-mire"
    assert build_url_slug("  <b>Тайтл</b> &amp; ещё  ") == "taytl-esche"
    assert build_url_slug("") == "manga"
    assert build_url_slug(None) == "manga"
    long_slug = build_url_slug("а" * 500)
    assert len(long_slug) <= 180
    assert not long_slug.endswith("-")


@pytest.mark.asyncio
async def test_import_assigns_and_api_exposes_url_slug(service) -> None:
    catalog, _session_factory = service
    result = await catalog.import_detail(detail("one-punch", title="Ванпанчмен"))
    assert result.manga.url_slug == "vanpanchmen"
    assert result.manga.slug == "one-punch"  # source-owned field stays separate

    fetched = await catalog.manga_detail(result.manga.id)
    assert fetched.url_slug == "vanpanchmen"

    listed = await catalog.list(query="Ванпанчмен")
    assert listed.items[0].url_slug == "vanpanchmen"


@pytest.mark.asyncio
async def test_duplicate_titles_get_distinct_urls_via_uuid(service) -> None:
    catalog, _session_factory = service
    first = await catalog.import_detail(detail("same-a", title="Одинаковый тайтл"))
    second = await catalog.import_detail(detail("same-b", title="Одинаковый тайтл"))

    assert first.manga.url_slug == second.manga.url_slug == "odinakovyy-taytl"
    assert first.manga.id != second.manga.id
    assert f"/manga/{first.manga.id}-{first.manga.url_slug}" != (
        f"/manga/{second.manga.id}-{second.manga.url_slug}"
    )


@pytest.mark.asyncio
async def test_backfill_is_batched_resumable_and_idempotent(service) -> None:
    catalog, session_factory = service
    for index in range(5):
        await catalog.import_detail(detail(f"title-{index}", title=f"Тайтл {index}"))

    async with session_factory() as session:
        rows = list((await session.scalars(select(Manga))).all())
        for row in rows:
            row.url_slug = None
        await session.commit()

    async with session_factory() as session:
        updated_before = {
            row.id: row.updated_at
            for row in (await session.scalars(select(Manga))).all()
        }

    async with session_factory() as session:
        assert await backfill_url_slugs(session, batch_size=2) == 2
        await session.commit()
    async with session_factory() as session:
        assert await backfill_url_slugs(session, batch_size=2) == 2
        await session.commit()
    async with session_factory() as session:
        assert await backfill_url_slugs(session, batch_size=2) == 1
        await session.commit()

    async with session_factory() as session:
        rows = list((await session.scalars(select(Manga))).all())
        assert all(row.url_slug for row in rows)
        # Slug backfill must not make every title look freshly modified.
        assert all(row.updated_at == updated_before[row.id] for row in rows)
        assert await backfill_url_slugs(session, batch_size=2) == 0

    # The high-level worker is also safe to run when everything is filled.
    assert await run_slug_backfill(session_factory, batch_size=2, yield_seconds=0) == 0


@pytest.mark.asyncio
async def test_runtime_migration_adds_url_slug_to_existing_sqlite(tmp_path: Path) -> None:
    settings = CatalogSettings(
        service_name="catalog-slug-migration-test",
        catalog_database_url=f"sqlite+aiosqlite:///{(tmp_path / 'legacy.db').as_posix()}",
    )
    engine = create_engine(settings.catalog_dsn)
    await create_all(engine)
    async with engine.begin() as connection:
        await connection.execute(text("DROP INDEX IF EXISTS ix_manga_url_slug"))
        await connection.execute(text("ALTER TABLE manga DROP COLUMN url_slug"))

    await ensure_runtime_schema(engine)
    async with engine.begin() as connection:
        result = await connection.execute(text("PRAGMA table_info(manga)"))
        columns = {row[1] for row in result.fetchall()}
    assert "url_slug" in columns
    await engine.dispose()


@pytest.mark.asyncio
async def test_sitemap_excludes_adult_titles_and_uses_slugs(service) -> None:
    catalog, _session_factory = service
    safe = await catalog.import_detail(detail("safe", title="Безопасный тайтл"))
    adult = await catalog.import_detail(detail("adult", title="Взрослый тайтл", adult=True))

    entries = await catalog.sitemap_entries()
    ids = {entry.id for entry in entries}
    assert safe.manga.id in ids
    assert adult.manga.id not in ids
    assert all(entry.url_slug for entry in entries)
    assert all(entry.title for entry in entries)
