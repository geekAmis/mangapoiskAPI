from __future__ import annotations

from pathlib import Path

import pytest
from manga_common.db import create_all, create_engine, create_session_factory
from manga_common.source_models import MangaSummary
from services.catalog.app.config import CatalogSettings
from services.catalog.app.migrations import ensure_runtime_schema
from services.catalog.app.service import CatalogService
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.fixtures.sample import sample_manga


async def make_service(
    tmp_path: Path, name: str = "filters.db"
) -> tuple[CatalogService, AsyncEngine]:
    db_path = tmp_path / name
    settings = CatalogSettings(
        service_name="catalog-test",
        catalog_database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
    )
    engine = create_engine(settings.catalog_dsn)
    await create_all(engine)
    service = CatalogService(settings, create_session_factory(engine), None)  # type: ignore[arg-type]
    return service, engine


def manga_summary(
    source_id: str,
    *,
    status: str | None = None,
    genres: list[str] | None = None,
    description: str | None = None,
) -> MangaSummary:
    return MangaSummary(
        source="mangapoisk",
        source_id=source_id,
        title=f"Title {source_id}",
        status=status,
        genres=genres or [],
        description=description,
    )


@pytest.mark.asyncio
async def test_status_and_genre_filters_are_normalized(tmp_path: Path) -> None:
    service, engine = await make_service(tmp_path)
    rows = [
        ("ongoing-ru", "Онгоинг", ["Фэнтези", "Приключения", "Комедия"]),
        ("ongoing-en", "ongoing", ["Романтика", "Драма", "Фэнтези"]),
        ("completed-ru", "Завершён", []),
        ("completed-en", "completed", []),
        ("announced-ru", "Анонс", []),
        ("dropped-ru", "Брошен", []),
        ("paused-ru", "На паузе", []),
        ("cancelled-ru", "Отменён", []),
        ("licensed-ru", "Лицензировано", []),
        ("unknown-ru", "Неизвестно", []),
    ]
    for source_id, status, genres in rows:
        await service.import_summary(
            manga_summary(source_id, status=status, genres=genres, description=f"About {source_id}")
        )

    status_cases = [
        ("ongoing", 2),
        ("Продолжается", 2),
        ("ONGOING", 2),
        ("оНгОиНг", 2),
        ("completed", 2),
        ("Завершён", 2),
        ("завершен", 2),
        ("announced", 1),
        ("Анонс", 1),
        ("dropped", 1),
        ("Брошен", 1),
        ("paused", 1),
        ("hiatus", 1),
        ("На паузе", 1),
        ("cancelled", 1),
        ("canceled", 1),
        ("Отменён", 1),
        ("licensed", 1),
        ("unknown", 1),
    ]
    for query, expected_total in status_cases:
        result = await service.list(status=query, include_empty=True)
        assert result.total == expected_total, f"status={query!r}"
        assert len(result.items) == expected_total, f"status={query!r}"

    genre_cases = [
        ("Фэнтези", 2),
        ("фэнтези", 2),
        ("ФЭНТЕЗИ", 2),
        ("Приключения", 1),
        ("приключения", 1),
        ("Драма", 1),
        ("Комедия", 1),
        ("Несуществующий", 0),
    ]
    for query, expected_total in genre_cases:
        result = await service.list(genre=query, include_empty=True)
        assert result.total == expected_total, f"genre={query!r}"
        assert len(result.items) == expected_total, f"genre={query!r}"

    combined = await service.list(genre="Фэнтези", status="ongoing", include_empty=True)
    assert combined.total == 2
    assert {item.source_id for item in combined.items} == {"ongoing-ru", "ongoing-en"}

    second_page = await service.list(genre="Фэнтези", page=2, limit=1, include_empty=True)
    assert second_page.total == 2
    assert len(second_page.items) == 1
    assert second_page.has_next is False

    no_match = await service.list(status="nosuchstatus", include_empty=True)
    assert no_match.total == 0
    assert no_match.items == []
    no_genre_match = await service.list(genre="Несуществующий", include_empty=True)
    assert no_genre_match.total == 0
    assert no_genre_match.items == []

    await engine.dispose()


@pytest.mark.asyncio
async def test_empty_summary_genres_do_not_erase_enriched_metadata(tmp_path: Path) -> None:
    service, engine = await make_service(tmp_path, "preserve.db")
    await service.import_detail(sample_manga())

    await service.import_summary(
        MangaSummary(
            source="mangapoisk",
            source_id="sample-manga",
            title="Пример манги",
            genres=[],
            description=None,
        )
    )

    result = await service.list(genre="фэнтези")
    assert result.total == 1
    assert result.items[0].genres == ["фэнтези", "приключения"]
    assert result.items[0].description

    await engine.dispose()


@pytest.mark.asyncio
async def test_runtime_migration_backfills_filter_keys(tmp_path: Path) -> None:
    service, engine = await make_service(tmp_path, "migration.db")
    await service.import_summary(
        manga_summary("legacy", status="Онгоинг", genres=["Фэнтези", "Комедия"])
    )
    async with engine.begin() as connection:
        await connection.execute(text("UPDATE manga SET status_key = NULL, genres_key = NULL"))

    await ensure_runtime_schema(engine)

    by_status = await service.list(status="ongoing", include_empty=True)
    assert by_status.total == 1
    by_genre = await service.list(genre="комедия", include_empty=True)
    assert by_genre.total == 1
    assert by_genre.items[0].source_id == "legacy"

    await engine.dispose()
