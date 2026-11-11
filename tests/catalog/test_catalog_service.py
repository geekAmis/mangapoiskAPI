from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from manga_common.db import create_all, create_engine, create_session_factory
from manga_common.errors import NotFoundError
from services.catalog.app.config import CatalogSettings
from services.catalog.app.service import CatalogService

from tests.fixtures.sample import sample_chapter_detail, sample_manga, sample_search


class FakeParser:
    def __init__(self) -> None:
        self.manga_calls = 0
        self.chapter_calls = 0

    async def manga(self, source: str, *, source_id=None, url=None):  # type: ignore[no-untyped-def]
        self.manga_calls += 1
        return sample_manga()

    async def chapter(self, source: str, *, source_id=None, url=None):  # type: ignore[no-untyped-def]
        self.chapter_calls += 1
        return sample_chapter_detail()

    async def sources(self):  # type: ignore[no-untyped-def]
        return [sample_search().items[0]]


@pytest.mark.asyncio
async def test_catalog_import_search_and_pages(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.db"
    settings = CatalogSettings(
        service_name="catalog-test",
        catalog_database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
    )
    engine = create_engine(settings.catalog_dsn)
    session_factory = create_session_factory(engine)
    await create_all(engine)
    parser = FakeParser()
    service = CatalogService(settings, session_factory, parser)  # type: ignore[arg-type]

    result = await service.import_detail(sample_manga())
    assert result.created is True
    assert result.manga.title == "Пример манги"
    assert len(result.manga.chapters) == 3
    assert result.imported_chapters == 3

    again = await service.import_detail(sample_manga(chapters=5))
    assert again.created is False
    assert again.imported_chapters == 2

    listing = await service.list(query="Пример")
    assert listing.total == 1
    assert listing.items[0].genres == ["фэнтези", "приключения"]

    detail = await service.manga_detail(result.manga.id)
    assert detail.chapters_count == 5
    assert detail.chapters[0].number == "5"

    chapter_id = detail.chapters[-1].id
    chapter = await service.chapter_detail(chapter_id)
    assert len(chapter.pages) == 3
    assert chapter.pages[0]["number"] == 1
    assert chapter.prev_chapter_id is None
    assert chapter.next_chapter_id == detail.chapters[-2].id

    # Cached pages should be served without another upstream call.
    calls_before = parser.chapter_calls
    cached = await service.chapter_detail(chapter_id)
    assert len(cached.pages) == 3
    assert parser.chapter_calls == calls_before

    await engine.dispose()


@pytest.mark.asyncio
async def test_catalog_import_summary_and_missing(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog2.db"
    settings = CatalogSettings(
        service_name="catalog-test",
        catalog_database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
    )
    engine = create_engine(settings.catalog_dsn)
    session_factory = create_session_factory(engine)
    await create_all(engine)
    service = CatalogService(settings, session_factory, FakeParser())  # type: ignore[arg-type]

    summary = sample_search().items[0]
    manga = await service.import_summary(summary)
    assert manga.title == summary.title
    assert manga.chapters_count == 0

    with pytest.raises(NotFoundError):
        await service.manga_detail(uuid.uuid4())
    await engine.dispose()
