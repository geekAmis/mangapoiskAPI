from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from manga_common.db import create_all, create_engine, create_session_factory
from manga_common.errors import NotFoundError
from manga_common.source_models import ChapterSummary, MangaDetail
from services.catalog.app.config import CatalogSettings
from services.catalog.app.recommendations import clear_recommendation_cache
from services.catalog.app.schemas import RecommendationRequest, RelationIn, RelationsIn
from services.catalog.app.service import CatalogService


def detail(
    source_id: str,
    *,
    title: str,
    genres: list[str],
    chapters: int = 1,
    rating: float | None = 7.0,
    rating_count: int = 100,
    days_ago: int = 20,
) -> MangaDetail:
    now = datetime.now(UTC) - timedelta(days=days_ago)
    return MangaDetail(
        source="test",
        source_id=source_id,
        slug=source_id,
        title=title,
        year=2024,
        rating=rating,
        rating_count=rating_count,
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
async def catalog(tmp_path: Path):
    db_path = tmp_path / "recommendations.db"
    settings = CatalogSettings(
        service_name="catalog-recommendation-test",
        catalog_database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
    )
    engine = create_engine(settings.catalog_dsn)
    await create_all(engine)
    service = CatalogService(settings, create_session_factory(engine), None)  # type: ignore[arg-type]
    clear_recommendation_cache()
    try:
        yield service
    finally:
        await engine.dispose()
        clear_recommendation_cache()


async def seed_five_reads(service: CatalogService) -> list[uuid.UUID]:
    read_ids: list[uuid.UUID] = []
    specs = [
        ("read-1", "Хроники клинка", ["Фэнтези", "Боевик"], 9.0),
        ("read-2", "Академия магии", ["Фэнтези", "Романтика"], 8.6),
        ("read-3", "Городской охотник", ["Боевик", "Ужасы"], 8.2),
        ("read-4", "Тайна старой башни", ["Мистика", "Приключения"], 7.9),
        ("read-5", "Королевство пепла", ["Фэнтези", "Драма"], 8.4),
    ]
    for source_id, title, genres, rating in specs:
        result = await service.import_detail(
            detail(source_id, title=title, genres=genres, chapters=12, rating=rating)
        )
        read_ids.append(result.manga.id)
    return read_ids


@pytest.mark.asyncio
async def test_recommendations_after_five_reads_are_plausible_and_clean(
    catalog: CatalogService,
) -> None:
    read_ids = await seed_five_reads(catalog)
    good_ids: list[uuid.UUID] = []
    for index in range(12):
        genres = ["Фэнтези", "Боевик"] if index % 2 == 0 else ["Романтика", "Драма"]
        result = await catalog.import_detail(
            detail(
                f"good-{index}",
                title=f"Кандидат {index}",
                genres=genres,
                chapters=5 + index,
                rating=7.0 + (index % 5) * 0.4,
                rating_count=500 + index * 100,
                days_ago=index * 10,
            )
        )
        good_ids.append(result.manga.id)
    # Empty catalogue stubs must never enter recommendations.
    stub = await catalog.import_detail(
        detail("stub", title="Пустой тайтл", genres=["Фэнтези"], chapters=0)
    )
    assert stub.manga.chapters_count == 0

    result = await catalog.recommendations(
        RecommendationRequest(history_ids=read_ids, limit=12)
    )
    assert result.strategy == "personalized"
    assert 6 <= len(result.items) <= 12
    ids = [item.id for item in result.items]
    assert len(ids) == len(set(ids))
    assert not set(ids) & set(read_ids)
    assert stub.manga.id not in ids
    assert all(item.chapters_count > 0 for item in result.items)
    assert all(item.title and item.title != "Пустой тайтл" for item in result.items)
    # The history is fantasy/action-heavy, so the shelf should reflect it.
    preferred = {"fantasy", "action"}
    assert sum(1 for item in result.items if preferred & set(item.genre_slugs or [])) >= 6


@pytest.mark.asyncio
async def test_cold_start_and_explicit_exclusions(catalog: CatalogService) -> None:
    for index in range(8):
        await catalog.import_detail(
            detail(
                f"cold-{index}",
                title=f"Тайтл {index}",
                genres=["Фэнтези"] if index % 2 == 0 else ["Ужасы"],
                chapters=3,
                rating=6.5 + index * 0.3,
                rating_count=100 + index * 50,
                days_ago=index * 5,
            )
        )

    cold = await catalog.recommendations(RecommendationRequest(limit=8))
    assert cold.strategy == "popular"
    assert len(cold.items) == 8
    assert all(item.chapters_count > 0 for item in cold.items)

    excluded = cold.items[0].id
    filtered = await catalog.recommendations(
        RecommendationRequest(exclude_ids=[excluded], limit=8)
    )
    assert excluded not in [item.id for item in filtered.items]
    assert len(filtered.items) == 7


@pytest.mark.asyncio
async def test_series_and_related_links_are_explicit(catalog: CatalogService) -> None:
    series_a = await catalog.import_detail(
        detail("cycle-a", title="Цикл: Начало", genres=["Фэнтези"], chapters=10)
    )
    series_b = await catalog.import_detail(
        detail("cycle-b", title="Цикл: Продолжение", genres=["Фэнтези"], chapters=10)
    )
    series_c = await catalog.import_detail(
        detail("cycle-c", title="Цикл: Финал", genres=["Фэнтези"], chapters=10)
    )
    related_d = await catalog.import_detail(
        detail("related-d", title="Похожий тайтл", genres=["Боевик"], chapters=8)
    )
    stub = await catalog.import_detail(
        detail("stub-related", title="Пустая связь", genres=["Фэнтези"], chapters=0)
    )

    linked = await catalog.link_relations(
        series_a.manga.id,
        RelationsIn(
            items=[
                RelationIn(
                    to_manga_id=series_b.manga.id,
                    relation="series",
                    series_key="cycle-x",
                ),
                RelationIn(
                    to_manga_id=series_c.manga.id,
                    relation="series",
                    series_key="cycle-x",
                ),
                RelationIn(
                    to_manga_id=related_d.manga.id,
                    relation="related",
                ),
                RelationIn(
                    to_manga_id=stub.manga.id,
                    relation="related",
                ),
            ]
        ),
    )
    assert linked.linked == 4

    # A -> B and A -> C share a series_key, so opening B still sees the full cycle.
    relation_b = await catalog.related(series_b.manga.id)
    assert {item.id for item in relation_b.series} == {
        series_a.manga.id,
        series_c.manga.id,
    }
    assert relation_b.related == []

    relation_a = await catalog.related(series_a.manga.id)
    assert {item.id for item in relation_a.series} == {
        series_b.manga.id,
        series_c.manga.id,
    }
    assert {item.id for item in relation_a.related} == {related_d.manga.id}
    # Empty-chapter titles are filtered out of navigation.
    assert stub.manga.id not in {item.id for item in relation_a.related}

    with pytest.raises(NotFoundError):
        await catalog.link_relations(
            series_a.manga.id,
            RelationsIn(items=[RelationIn(to_manga_id=series_a.manga.id)]),
        )
