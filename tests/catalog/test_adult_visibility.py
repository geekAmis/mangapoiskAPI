from __future__ import annotations

from pathlib import Path

import pytest
from manga_common.db import create_all, create_engine, create_session_factory
from manga_common.errors import ForbiddenError
from manga_common.source_models import SourceCapabilities, SourceInfo
from services.catalog.app.config import CatalogSettings
from services.catalog.app.migrations import ensure_runtime_schema
from services.catalog.app.schemas import RecommendationRequest
from services.catalog.app.service import CatalogService
from sqlalchemy import text

from tests.fixtures.sample import sample_chapter_detail, sample_manga


class FakeParser:
    async def manga(self, source: str, *, source_id=None, url=None):  # type: ignore[no-untyped-def]
        raise AssertionError("not used")

    async def chapter(self, source: str, *, source_id=None, url=None):  # type: ignore[no-untyped-def]
        return sample_chapter_detail()


def _adult_manga():  # type: ignore[no-untyped-def]
    return sample_manga().model_copy(
        update={
            "source_id": "adult-1",
            "slug": "adult-1",
            "title": "Взрослый тайтл",
            "adult": True,
            "adult_only": True,
            "requires_age_confirmation": True,
            "url": "https://hentailib.me/ru/manga/adult-1",
        }
    )


async def _service(tmp_path: Path) -> CatalogService:
    db_path = tmp_path / "catalog.db"
    settings = CatalogSettings(
        service_name="catalog-adult-test",
        catalog_database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
    )
    engine = create_engine(settings.catalog_dsn)
    session_factory = create_session_factory(engine)
    await create_all(engine)
    return CatalogService(settings, session_factory, FakeParser())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_adult_titles_are_hidden_from_public_surfaces(tmp_path: Path) -> None:
    service = await _service(tmp_path)
    normal = await service.import_detail(sample_manga())
    adult = await service.import_detail(_adult_manga())

    public = await service.list(limit=50)
    assert {item.id for item in public.items} == {normal.manga.id}

    allowed = await service.list(limit=50, adult_allowed=True)
    assert {item.id for item in allowed.items} == {normal.manga.id, adult.manga.id}

    suggestions = await service.suggest("Пример", limit=10)
    assert all(item.id != adult.manga.id for item in suggestions.items)

    sitemap = await service.sitemap_entries()
    assert all(row.id != adult.manga.id for row in sitemap)

    recommendations = await service.recommendations(RecommendationRequest(limit=10))
    assert all(item.id != adult.manga.id for item in recommendations.items)

    genres = await service.genres()
    counts = {item.slug: item.count for item in genres.items}
    assert counts.get("fantasy") == 1


@pytest.mark.asyncio
async def test_direct_adult_routes_require_confirmation(tmp_path: Path) -> None:
    service = await _service(tmp_path)
    adult = await service.import_detail(_adult_manga())
    chapter_id = adult.manga.chapters[0].id

    with pytest.raises(ForbiddenError) as blocked:
        await service.manga_detail(adult.manga.id)
    assert blocked.value.code == "age_confirmation_required"

    with pytest.raises(ForbiddenError):
        await service.chapters(adult.manga.id)

    with pytest.raises(ForbiddenError):
        await service.chapter_detail(chapter_id)

    with pytest.raises(ForbiddenError):
        await service.chapter_meta(chapter_id)

    with pytest.raises(ForbiddenError):
        await service.variants(adult.manga.id)

    detail = await service.manga_detail(adult.manga.id, adult_allowed=True)
    assert detail.adult_only is True
    assert detail.chapters[0].adult_only is True

    chapter = await service.chapter_detail(chapter_id, adult_allowed=True)
    assert chapter.adult_only is True
    assert chapter.requires_age_confirmation is True


@pytest.mark.asyncio
async def test_runtime_migration_adds_adult_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy-catalog.db"
    settings = CatalogSettings(
        service_name="catalog-migration-test",
        catalog_database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
    )
    engine = create_engine(settings.catalog_dsn)
    await create_all(engine)
    async with engine.begin() as connection:
        await connection.execute(text("DROP INDEX IF EXISTS ix_manga_adult_only"))
        await connection.execute(text("ALTER TABLE manga DROP COLUMN adult_only"))
        await connection.execute(text("ALTER TABLE manga DROP COLUMN requires_age_confirmation"))
        await connection.execute(text("ALTER TABLE sources DROP COLUMN adult_only"))
        await connection.execute(
            text("ALTER TABLE sources DROP COLUMN requires_age_confirmation")
        )

    await ensure_runtime_schema(engine)
    async with engine.begin() as connection:
        manga_columns = {
            row[1]
            for row in (
                await connection.execute(text("PRAGMA table_info(manga)"))
            ).fetchall()
        }
        source_columns = {
            row[1]
            for row in (
                await connection.execute(text("PRAGMA table_info(sources)"))
            ).fetchall()
        }
    assert {"adult_only", "requires_age_confirmation"} <= manga_columns
    assert {"adult_only", "requires_age_confirmation"} <= source_columns
    await engine.dispose()


@pytest.mark.asyncio
async def test_adult_source_rows_are_hidden_without_confirmation(tmp_path: Path) -> None:
    service = await _service(tmp_path)
    await service.sync_sources(
        [
            SourceInfo(
                code="hentailib",
                name="HentaiLib",
                base_url="https://hentailib.me",
                enabled=False,
                adult_only=True,
                requires_age_confirmation=True,
                capabilities=SourceCapabilities(search=True, manga=True),
            )
        ]
    )

    assert all(row.code != "hentailib" for row in await service.source_rows())
    allowed = await service.source_rows(adult_allowed=True)
    assert any(row.code == "hentailib" for row in allowed)
