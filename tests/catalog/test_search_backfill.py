from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import pytest
from manga_common.db import create_all, create_engine, create_session_factory
from services.catalog.app.config import CatalogSettings
from services.catalog.app.migrations import ensure_runtime_schema
from services.catalog.app.models import Manga, SearchBackfillState
from services.catalog.app.search_backfill import (
    BackfillConfig,
    SearchBackfillWorker,
    bootstrap_search_index,
    retry_on_locked,
)
from services.catalog.app.search_fts import fts_available
from services.catalog.app.service import CatalogService
from sqlalchemy import func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import OperationalError


async def _seed_legacy(
    engine,  # type: ignore[no-untyped-def]
    count: int,
    *,
    name: str = "backfill",
) -> list[str]:
    ids: list[str] = []
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO sources (code, name, base_url, language, enabled, "
                "requires_cookies, capabilities) VALUES "
                "('mangapoisk','MangaPoisk','https://example','ru',1,0,'{}')"
            )
        )
        for index in range(count):
            manga_id = uuid.uuid4().hex
            ids.append(manga_id)
            title = "Человек-бензопила" if index == 0 else f"Тестовый тайтл {index}"
            title_en = "Chainsaw Man" if index == 0 else f"Test Title {index}"
            await connection.execute(
                text(
                    "INSERT INTO manga (id, source, source_id, slug, title, "
                    "title_en, title_alt, description, year, status, content_type, "
                    "rating, rating_count, adult, genres, metadata, search_title, "
                    "search_alt, search_names, search_meta, search_description, "
                    "search_blob, search_indexed, group_key, chapters_count, "
                    "enrichment_attempts) VALUES "
                    "(:id,'mangapoisk',:source_id,:source_id,:title,:title_en,NULL,"
                    ":description,2020,'ongoing','манга',8.5,1000,0,:genres,'{}',"
                    "'','','','','','',0,:group_key,10,0)"
                ),
                {
                    "id": manga_id,
                    "source_id": f"{name}-{index}",
                    "title": title,
                    "title_en": title_en,
                    "description": "Описание тайтла для поиска.",
                    "genres": json.dumps(["Экшен"], ensure_ascii=False),
                    "group_key": f"{name}-group-{index}",
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO chapters (id, manga_id, source, source_id, number, "
                    "title, page_count, is_external, is_horizontal) VALUES "
                    "(:id,:manga_id,'mangapoisk',:source_id,'1','Глава 1',16,0,0)"
                ),
                {
                    "id": uuid.uuid4().hex,
                    "manga_id": manga_id,
                    "source_id": f"{name}-chapter-{index}",
                },
            )
    return ids


@pytest.fixture()
async def backfill_env(tmp_path: Path):
    db_path = tmp_path / "backfill.db"
    settings = CatalogSettings(
        service_name="catalog-backfill-test",
        catalog_database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
    )
    engine = create_engine(settings.catalog_dsn)
    await create_all(engine)
    try:
        yield settings, engine, create_session_factory(engine)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_startup_is_quick_and_leaves_rows_for_worker(backfill_env) -> None:
    settings, engine, factory = backfill_env
    await _seed_legacy(engine, 2_000)

    started = time.perf_counter()
    await ensure_runtime_schema(engine)
    elapsed = time.perf_counter() - started
    # The old implementation ran build_search_fields for every row and took
    # minutes on production.  Schema-only startup has a wide but meaningful
    # budget even on a slow CI Windows runner.
    assert elapsed < 5.0

    async with factory() as session:
        pending = await session.scalar(
            select(func.count(Manga.id)).where(Manga.search_indexed.is_(False))
        )
        blobs = await session.scalar(
            select(func.count(Manga.id)).where(Manga.search_blob == "")
        )
    assert pending == 2_000
    assert blobs == 2_000

    service = CatalogService(settings, factory, None)  # type: ignore[arg-type]
    await bootstrap_search_index(factory, batch_size=500)
    before = await service.list(query="человек бензопила", limit=3)
    assert before.items and before.items[0].source_id == "backfill-0"
    async with factory() as session:
        assert await fts_available(session)
        assert int((await session.scalar(text("SELECT count(*) FROM manga_search_fts"))) or 0) == 2_000


@pytest.mark.asyncio
async def test_partial_backfill_search_and_resume(backfill_env) -> None:
    settings, engine, factory = backfill_env
    await _seed_legacy(engine, 12)
    await ensure_runtime_schema(engine)
    await bootstrap_search_index(factory, batch_size=5)
    service = CatalogService(settings, factory, None)  # type: ignore[arg-type]

    first_worker = SearchBackfillWorker(
        factory,
        BackfillConfig(batch_size=3, yield_seconds=0.0),
        owner="first-run",
    )
    assert await first_worker.step() == 3

    # The target may still be unindexed; legacy FTS + ranking_view must serve it.
    during = await service.list(query="человек бензопила", limit=3)
    assert during.items and during.items[0].source_id == "backfill-0"
    # Bounded pending-row scan keeps typo/transliteration suggestions useful
    # even before the worker reaches this title.
    suggestions = await service.suggest("чензо мен", limit=3)
    assert suggestions.items and suggestions.items[0].title == "Человек-бензопила"

    async with factory() as session:
        normalized = await session.scalar(
            select(func.count(Manga.id)).where(Manga.search_indexed.is_(True))
        )
        state = await session.get(SearchBackfillState, 1)
    assert normalized == 3
    assert state is not None and state.normalized == 3

    # Simulate a process restart: a new worker resumes from the remaining rows.
    second_worker = SearchBackfillWorker(
        factory,
        BackfillConfig(batch_size=3, yield_seconds=0.0),
        owner="second-run",
    )
    processed = await second_worker.backfill()
    assert processed == 9
    await second_worker.backfill_group_keys()
    await second_worker.backfill_cover_group_keys()

    async with factory() as session:
        normalized = await session.scalar(
            select(func.count(Manga.id)).where(Manga.search_indexed.is_(True))
        )
        total = await session.scalar(select(func.count(Manga.id)))
        state = await session.get(SearchBackfillState, 1)
        fts_rows = await session.scalar(text("SELECT count(*) FROM manga_search_fts"))
        duplicates = await session.scalar(
            text(
                "SELECT count(*) FROM (SELECT manga_id FROM manga_search_fts "
                "GROUP BY manga_id HAVING count(*) > 1)"
            )
        )
    assert normalized == total == 12
    assert state is not None and state.status == "completed"
    assert fts_rows == 12
    assert duplicates == 0

    # A second run must do no work.
    third_worker = SearchBackfillWorker(
        factory,
        BackfillConfig(batch_size=3, yield_seconds=0.0),
        owner="third-run",
    )
    assert await third_worker.step() == 0
    async with factory() as session:
        state = await session.get(SearchBackfillState, 1)
    assert state is not None and state.normalized == 12


@pytest.mark.asyncio
async def test_lock_retry_backoff() -> None:
    calls = 0

    async def flaky() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise OperationalError(
                "UPDATE manga", {}, Exception("database is locked")
            )
        return "ok"

    assert await retry_on_locked(flaky, attempts=4, base_delay=0.0) == "ok"
    assert calls == 3


def test_postgres_legacy_fallback_compiles() -> None:
    from services.catalog.app.repository import _legacy_filter, _legacy_search_text

    statement = select(Manga.id).where(
        Manga.search_indexed.is_(False),
        _legacy_search_text().contains("чензо"),
    )
    compiled = str(statement.compile(dialect=postgresql.dialect()))
    assert "lower" in compiled
    assert "LIKE" in compiled

    filter_clause = _legacy_filter(["чензо", "мен"])
    compiled_filter = str(
        select(Manga.id).where(filter_clause).compile(dialect=postgresql.dialect())
    )
    assert "search_indexed IS false" in compiled_filter
