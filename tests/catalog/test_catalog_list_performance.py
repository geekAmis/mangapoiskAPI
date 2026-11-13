from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest
from manga_common.db import create_all, create_engine, create_session_factory
from manga_common.source_models import ChapterSummary, MangaDetail, MangaSummary
from services.catalog.app.config import CatalogSettings
from services.catalog.app.migrations import ensure_runtime_schema
from services.catalog.app.models import CatalogGroup, Chapter, Manga
from services.catalog.app.observability import install_slow_query_logging
from services.catalog.app.repository import ensure_source
from services.catalog.app.service import CatalogService
from sqlalchemy import func, select, text, update


async def make_service(
    tmp_path: Path, name: str = "list-performance.db"
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


def detail(
    source_id: str,
    *,
    title: str,
    genres: list[str] | None = None,
    chapters: int = 1,
    chapters_count: int | None = None,
) -> MangaDetail:
    return MangaDetail(
        source="mangapoisk",
        source_id=source_id,
        slug=source_id,
        title=title,
        description=f"Описание {title}",
        genres=genres or [],
        chapters=[
            ChapterSummary(
                source="mangapoisk",
                source_id=f"{source_id}-{number}",
                manga_source_id=source_id,
                number=str(number),
                title=f"Глава {number}",
                published_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
            for number in range(1, chapters + 1)
        ],
        chapters_count=chapters_count,
    )


@pytest.mark.asyncio
async def test_list_never_returns_cards_without_chapter_rows(tmp_path: Path) -> None:
    service, engine = await make_service(tmp_path)

    # A search summary can know a source-reported chapter count before the
    # detail import.  It must stay hidden until real chapter rows exist.
    await service.import_summary(
        MangaSummary(
            source="mangapoisk",
            source_id="summary-only",
            title="Только саммари",
            chapters_count=42,
        )
    )
    # The same failure mode through the detail endpoint: the source claims
    # chapters, but the payload contains none.
    await service.import_detail(
        detail("detail-empty", title="Пустой детал", chapters=0, chapters_count=50)
    )
    for index in range(3):
        await service.import_detail(
            detail(f"visible-{index}", title=f"Видимый тайтл {index}", chapters=2)
        )

    listing = await service.list(limit=10)
    assert listing.total == 3
    assert {item.source_id for item in listing.items} == {
        "visible-0",
        "visible-1",
        "visible-2",
    }

    async with service.session_factory() as session:
        for item in listing.items:
            chapter_rows = await session.scalar(
                select(func.count(Chapter.id)).where(Chapter.manga_id == item.id)
            )
            assert chapter_rows and chapter_rows > 0
            manga = await session.get(Manga, item.id)
            assert manga is not None and manga.has_chapters is True

    # include_empty is the explicit QA/admin escape hatch and still exposes the
    # stubs, without changing the public list contract.
    with_empty = await service.list(include_empty=True, limit=10)
    assert with_empty.total == 5
    assert {"summary-only", "detail-empty"} <= {
        item.source_id for item in with_empty.items
    }
    await engine.dispose()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_materialised_list_dedupes_groups_and_is_stable_across_pages(
    tmp_path: Path,
) -> None:
    service, engine = await make_service(tmp_path, "stable.db")
    for index in range(6):
        await service.import_detail(
            detail(
                f"group-{index}-a",
                title=f"Стабильный тайтл {index}",
                genres=["фэнтези", "ужасы"],
                chapters=2,
            )
        )
        # Same canonical group: must not produce a second card.
        await service.import_detail(
            detail(
                f"group-{index}-b",
                title=f"Стабильный тайтл {index} (ремастер)",
                genres=["фэнтези"],
                chapters=3,
            )
        )

    # Force exact sort-key ties so only the deterministic group_key tiebreaker
    # decides the order.
    tied_at = datetime(2026, 2, 1, tzinfo=UTC)
    async with service.session_factory() as session:
        await session.execute(
            update(CatalogGroup).values(
                rating_count=0,
                rating=None,
                updated_at=tied_at,
                last_chapter_at=tied_at,
            )
        )
        await session.commit()

    first = await service.list(sort="popular", page=1, limit=2)
    second = await service.list(sort="popular", page=2, limit=2)
    third = await service.list(sort="popular", page=3, limit=2)
    assert first.total == second.total == third.total == 6
    ids = [item.id for page in (first, second, third) for item in page.items]
    assert len(ids) == len(set(ids)) == 6
    assert ids == [item.id for item in (await service.list(limit=6)).items]

    # Genre AND filters and status/title sorts still operate on the
    # materialised card table.
    both = await service.list(genres=["fantasy", "horror"], limit=10)
    assert both.total == 6
    assert all({"fantasy", "horror"} <= set(item.genre_slugs) for item in both.items)
    title_sorted = await service.list(sort="title", limit=10)
    assert [item.title for item in title_sorted.items] == sorted(
        item.title for item in title_sorted.items
    )
    await engine.dispose()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_source_filter_still_uses_variant_semantics(tmp_path: Path) -> None:
    service, engine = await make_service(tmp_path, "source-filter.db")
    await service.import_detail(
        MangaDetail(
            source="mangapoisk",
            source_id="source-a",
            slug="source-a",
            title="Источник теста",
            genres=["фэнтези"],
            chapters=[
                ChapterSummary(
                    source="mangapoisk",
                    source_id="source-a-1",
                    manga_source_id="source-a",
                    number="1",
                    title="Глава 1",
                )
            ],
        )
    )
    await service.import_detail(
        MangaDetail(
            source="mangalib",
            source_id="source-b",
            slug="source-b",
            title="Источник теста",
            genres=["фэнтези"],
            chapters=[
                ChapterSummary(
                    source="mangalib",
                    source_id="source-b-1",
                    manga_source_id="source-b",
                    number="1",
                    title="Глава 1",
                ),
                ChapterSummary(
                    source="mangalib",
                    source_id="source-b-2",
                    manga_source_id="source-b",
                    number="2",
                    title="Глава 2",
                ),
            ],
        )
    )

    unfiltered = await service.list(limit=10)
    assert unfiltered.total == 1
    assert unfiltered.items[0].source == "mangalib"

    mangapoisk = await service.list(source="mangapoisk", limit=10)
    assert mangapoisk.total == 1
    assert mangapoisk.items[0].source == "mangapoisk"
    assert mangapoisk.items[0].source_id == "source-a"

    mangalib = await service.list(source="mangalib", limit=10)
    assert mangalib.total == 1
    assert mangalib.items[0].source == "mangalib"
    assert mangalib.items[0].source_id == "source-b"
    await engine.dispose()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_runtime_migration_repairs_inconsistent_visibility(tmp_path: Path) -> None:
    db_path = tmp_path / "repair.db"
    settings = CatalogSettings(
        service_name="catalog-test",
        catalog_database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
    )
    engine = create_engine(settings.catalog_dsn)
    await create_all(engine)
    async with create_session_factory(engine)() as session:
        await ensure_source(session, "mangapoisk", "MangaPoisk")
        # Stale true flag, no chapter rows: production had 20 such rows.
        stale = Manga(
            source="mangapoisk",
            source_id="stale-flag",
            title="Устаревший флаг",
            chapters_count=12,
            has_chapters=True,
            group_key="stale-flag",
        )
        # Summary-like row: count is known, chapters are not imported.
        summary_only = Manga(
            source="mangapoisk",
            source_id="summary-only",
            title="Саммари без глав",
            chapters_count=7,
            has_chapters=False,
            group_key="summary-only",
        )
        # Real chapters but a stale false flag (e.g. a crashed import).
        real = Manga(
            source="mangapoisk",
            source_id="real-chapters",
            title="Настоящие главы",
            chapters_count=1,
            has_chapters=False,
            group_key="real-chapters",
        )
        session.add_all([stale, summary_only, real])
        await session.flush()
        session.add(
            Chapter(
                manga_id=real.id,
                source="mangapoisk",
                source_id="real-1",
                number="1",
                title="Глава 1",
            )
        )
        await session.commit()

    await ensure_runtime_schema(engine)
    service = CatalogService(settings, create_session_factory(engine), None)  # type: ignore[arg-type]
    listing = await service.list(limit=10)
    assert listing.total == 1
    assert [item.source_id for item in listing.items] == ["real-chapters"]

    async with service.session_factory() as session:
        flags = {
            row.source_id: row.has_chapters
            for row in (await session.scalars(select(Manga))).all()
        }
        cards = int((await session.scalar(select(func.count(CatalogGroup.group_key)))) or 0)
    assert flags == {
        "stale-flag": False,
        "summary-only": False,
        "real-chapters": True,
    }
    assert cards == 1
    await engine.dispose()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_list_latency_and_planner_stats_are_exposed(tmp_path: Path) -> None:
    service, engine = await make_service(tmp_path, "latency.db")
    await service.import_detail(detail("latency", title="Латентность", chapters=1))
    for _ in range(5):
        await service.list(limit=5)
    stats = await service.catalog_stats()
    assert stats.list_latency is not None
    assert stats.list_latency.samples == 5
    assert stats.list_latency.p50_ms >= 0
    assert stats.list_latency.p95_ms >= stats.list_latency.p50_ms

    optimized = await service.optimize_stats()
    assert optimized["dialect"] == "sqlite"
    assert optimized["duration_ms"] >= 0
    await engine.dispose()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_list_query_plan_uses_materialised_indexes(tmp_path: Path) -> None:
    service, engine = await make_service(tmp_path, "plan.db")
    for index in range(20):
        await service.import_detail(
            detail(f"plan-{index}", title=f"План {index}", chapters=1)
        )

    async with engine.connect() as connection:
        count_plan = (
            await connection.execute(text("EXPLAIN QUERY PLAN SELECT count(*) FROM catalog_groups"))
        ).all()
        popular_plan = (
            await connection.execute(
                text(
                    "EXPLAIN QUERY PLAN SELECT manga_id FROM catalog_groups "
                    "ORDER BY rating_count DESC, rating DESC, updated_at DESC, "
                    "group_key DESC LIMIT 20"
                )
            )
        ).all()
    count_text = " ".join(str(row[-1]) for row in count_plan)
    popular_text = " ".join(str(row[-1]) for row in popular_plan)
    assert "catalog_groups" in count_text
    # SQLite may report a covering index or a scan for the tiny fixture, but it
    # must never fall back to the old window/group-by plan over manga.
    assert "ix_catalog_groups_popular" in popular_text or "COVERING INDEX" in popular_text
    assert "manga" not in popular_text
    await engine.dispose()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_slow_sql_is_logged(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    _, engine = await make_service(tmp_path, "slow-sql.db")
    install_slow_query_logging(engine, threshold_ms=0)
    with caplog.at_level(logging.WARNING, logger="catalog.sql"):
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    assert any("slow SQL" in record.message for record in caplog.records)
    await engine.dispose()  # type: ignore[attr-defined]
