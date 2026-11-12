from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from manga_common.db import create_all, create_engine, create_session_factory
from manga_common.source_models import ChapterSummary, MangaDetail, MangaSummary
from services.catalog.app.config import CatalogSettings
from services.catalog.app.repository import find_manga_by_source
from services.catalog.app.schemas import EnrichmentFailureRequest
from services.catalog.app.service import CatalogService


async def make_service(tmp_path: Path, name: str) -> tuple[CatalogService, object]:
    db_path = tmp_path / name
    settings = CatalogSettings(
        service_name="catalog-test",
        catalog_database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
    )
    engine = create_engine(settings.catalog_dsn)
    await create_all(engine)
    service = CatalogService(settings, create_session_factory(engine), None)  # type: ignore[arg-type]
    return service, engine


def summary(
    *,
    source_id: str,
    title: str,
    rating: float | None = None,
    rating_count: int | None = None,
) -> MangaSummary:
    return MangaSummary(
        source="mangapoisk",
        source_id=source_id,
        slug=source_id,
        title=title,
        rating=rating,
        rating_count=rating_count,
        chapters_count=0,
    )


def detail(source_id: str, title: str) -> MangaDetail:
    return MangaDetail(
        source="mangapoisk",
        source_id=source_id,
        slug=source_id,
        title=title,
        description=f"Описание {title}",
        genres=["Фэнтези"],
        chapters=[
            ChapterSummary(
                source="mangapoisk",
                source_id=f"{source_id}-1",
                manga_source_id=source_id,
                number="1",
                title="Глава 1",
                published_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        ],
    )


@pytest.mark.asyncio
async def test_enrichment_queue_prioritises_popular_and_skips_retry_titles(
    tmp_path: Path,
) -> None:
    service, engine = await make_service(tmp_path, "queue.db")
    popular = await service.import_summary(
        summary(
            source_id="popular",
            title="Популярный",
            rating=9.0,
            rating_count=50000,
        )
    )
    await service.import_summary(
        summary(
            source_id="low",
            title="Непопулярный",
            rating=5.0,
            rating_count=5,
        )
    )

    first = await service.pending_enrichment(source="mangapoisk", limit=1)
    assert [item.source_id for item in first.items] == ["popular"]

    await service.record_enrichment_failure(
        popular.id, EnrichmentFailureRequest(error="403 Forbidden", kind="forbidden")
    )
    second = await service.pending_enrichment(source="mangapoisk", limit=5)
    assert [item.source_id for item in second.items] == ["low"]

    stats = await service.enrichment_stats(rate_per_minute=36)
    assert stats.pending == 1
    assert stats.retrying == 1
    assert stats.estimated_seconds > 0
    by_source = {item.source: (item.pending, item.retrying) for item in stats.sources}
    assert by_source["mangapoisk"] == (1, 1)

    # A successful detail import clears the retry clock and removes the title.
    await service.import_detail(detail("low", "Непопулярный"))
    stats = await service.enrichment_stats(rate_per_minute=36)
    assert stats.pending == 0
    assert stats.retrying == 1
    assert stats.last_success_at is not None
    await engine.dispose()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_rotate_enrichment_is_bounded(tmp_path: Path) -> None:
    service, engine = await make_service(tmp_path, "rotate.db")
    for index in range(4):
        await service.import_detail(detail(f"rotate-{index}", f"Rotate {index}"))

    queued = await service.rotate_enrichment(source="mangapoisk", limit=2)
    assert queued == 2
    pending = await service.pending_enrichment(source="mangapoisk", limit=10)
    assert len(pending.items) == 2

    queued_again = await service.reset_enrichment(source="mangapoisk", limit=1)
    assert queued_again == 1
    await engine.dispose()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_enrichment_failure_backoff_and_detail_success_clears_it(
    tmp_path: Path,
) -> None:
    service, engine = await make_service(tmp_path, "backoff.db")
    imported = await service.import_summary(
        summary(source_id="backoff", title="Backoff")
    )

    first = await service.record_enrichment_failure(
        imported.id, EnrichmentFailureRequest(error="timeout", kind="timeout")
    )
    second = await service.record_enrichment_failure(
        imported.id, EnrichmentFailureRequest(error="timeout", kind="timeout")
    )
    assert second["attempts"] == 2
    assert second["retry_at"] is not None
    assert first["retry_at"] != second["retry_at"]

    await service.import_detail(detail("backoff", "Backoff"))
    async with service.session_factory() as session:
        manga = await find_manga_by_source(session, "mangapoisk", "backoff")
        assert manga is not None
        assert manga.enrichment_attempts == 0
        assert manga.enrichment_retry_at is None
        assert manga.enrichment_last_error is None
    await engine.dispose()  # type: ignore[attr-defined]
