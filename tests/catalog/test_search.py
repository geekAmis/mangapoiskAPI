from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from manga_common.db import create_all, create_engine, create_session_factory
from services.catalog.app.config import CatalogSettings
from services.catalog.app.migrations import ensure_runtime_schema
from services.catalog.app.models import Manga
from services.catalog.app.search import analyze_query, build_search_fields, expansion_terms
from services.catalog.app.search_backfill import (
    BackfillConfig,
    SearchBackfillWorker,
    bootstrap_search_index,
)
from services.catalog.app.search_fts import fts_available
from services.catalog.app.service import CatalogService
from sqlalchemy import or_, select, text

from tests.catalog.relevance_cases import RELEVANCE_CASES
from tests.fixtures.search_titles import TITLES, detail_from_spec


class ExplodingParser:
    """Suggestions must never touch the parser/live-search client."""

    async def manga(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("parser.manga must not be called by search")

    async def chapter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("parser.chapter must not be called by search")

    async def sources(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("parser.sources must not be called by search")


@pytest.fixture()
async def search_service(tmp_path: Path):
    db_path = tmp_path / "search.db"
    settings = CatalogSettings(
        service_name="catalog-search-test",
        catalog_database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
    )
    engine = create_engine(settings.catalog_dsn)
    await create_all(engine)
    await ensure_runtime_schema(engine)
    service = CatalogService(settings, create_session_factory(engine), ExplodingParser())  # type: ignore[arg-type]
    for spec in TITLES:
        await service.import_detail(detail_from_spec(spec))
    try:
        yield service
    finally:
        await engine.dispose()


async def top_ids(service: CatalogService, query: str, **kwargs) -> list[str]:  # type: ignore[no-untyped-def]
    result = await service.list(query=query, limit=3, **kwargs)
    return [item.source_id for item in result.items]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "человек бензопила",
        "человек-бензопила",
        "ЧЕЛОВЕК БЕНЗОПИЛА",
        "chainsaw man",
        "Chainsaw Man",
        "chenso man",
        "ченсо мен",
        "чензо мен",
        "чензомен",
        "человек бензопил",
    ],
)
async def test_chainsaw_man_typo_translit_and_alt_titles(search_service, query: str) -> None:
    assert "chainsaw-man" in await top_ids(search_service, query)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    ["solo leveling", "Solo Leveling", "поднятие уровня", "соло левелинг", "соло левелинг"],
)
async def test_solo_leveling_relevance(search_service, query: str) -> None:
    assert "solo-leveling" in await top_ids(search_service, query)


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["overgeared", "Overgeared", "овергир", "овергир"])
async def test_overgeared_romaji_and_cyrillic(search_service, query: str) -> None:
    assert "overgeared" in await top_ids(search_service, query)


@pytest.mark.asyncio
async def test_author_and_artist_search(search_service) -> None:
    fujimoto = await search_service.list(query="Фудзимото", limit=3)
    assert fujimoto.items
    assert fujimoto.items[0].source_id == "chainsaw-man"
    assert fujimoto.items[0].authors == ["Тацуки Фудзимото"]

    murata = await search_service.list(query="Мурата", limit=3)
    assert murata.items
    assert murata.items[0].source_id == "one-punch-man"

    author_title = await search_service.list(query="фудзимото человек", limit=3)
    assert author_title.items[0].source_id == "chainsaw-man"

    # Author + title works even when the author is not part of the title.
    combined = await search_service.list(query="мурата ванпанчмен", limit=3)
    assert combined.items[0].source_id == "one-punch-man"


@pytest.mark.asyncio
async def test_author_search_false_positives(search_service) -> None:
    fujimoto = await search_service.list(query="Фудзимото", limit=5)
    ids = {item.source_id for item in fujimoto.items}
    assert ids.isdisjoint({"naruto", "death-note", "tokyo-ghoul"})

    murata = await search_service.list(query="Мурата", limit=5)
    ids = {item.source_id for item in murata.items}
    assert ids.isdisjoint({"naruto", "death-note", "chainsaw-man"})


@pytest.mark.asyncio
async def test_author_suggestions_are_local(search_service) -> None:
    suggestions = await search_service.suggest("Фудзимото", limit=4)
    assert suggestions.items
    assert suggestions.items[0].title == "Человек-бензопила"
    assert suggestions.items[0].authors == ["Тацуки Фудзимото"]
    assert suggestions.items[0].reason == "author"

    murata = await search_service.suggest("Мурата", limit=4)
    assert murata.items
    assert murata.items[0].title == "Ванпанчмен"


@pytest.mark.asyncio
async def test_typo_does_not_surface_short_token_noise(search_service) -> None:
    result = await search_service.list(query="чензо мен", limit=3)
    ids = [item.source_id for item in result.items]
    assert ids[0] == "chainsaw-man"
    assert "menhera-chan" not in ids
    assert "summoned-monster" not in ids


@pytest.mark.asyncio
async def test_relevance_set_top_3(search_service) -> None:
    for case in RELEVANCE_CASES:
        result = await search_service.list(query=case.query, limit=3)
        ids = {item.source_id for item in result.items}
        assert ids, f"{case.query!r} returned nothing"
        if case.all_expected:
            assert ids <= case.expected, f"{case.query!r} returned unrelated titles: {ids}"
        else:
            assert case.expected <= ids, f"{case.query!r} top-3: {ids}"


@pytest.mark.asyncio
async def test_existing_title_outranks_description_noise(search_service) -> None:
    result = await search_service.list(query="человек бензопила", limit=10)
    assert result.items[0].source_id == "chainsaw-man"
    # "Токийский гуль" only shares a generic "человек" in its description; it
    # must never outrank the actual title.
    ids = [item.source_id for item in result.items]
    assert "tokyo-ghoul" not in ids[:3]


@pytest.mark.asyncio
async def test_genre_text_and_filters_combine(search_service) -> None:
    action = await search_service.list(query="человек бензопила", genre="боевик", limit=10)
    assert action.items and action.items[0].source_id == "chainsaw-man"

    wrong_genre = await search_service.list(query="человек бензопила", genre="романтика")
    assert wrong_genre.total == 0

    by_year = await search_service.list(query="solo leveling", year=2018)
    assert by_year.items[0].source_id == "solo-leveling"
    by_wrong_year = await search_service.list(query="solo leveling", year=1999)
    assert by_wrong_year.total == 0

    completed = await search_service.list(query="токийский гуль", status="completed")
    assert completed.items[0].source_id == "tokyo-ghoul"


@pytest.mark.asyncio
async def test_synonyms_media_types_and_reading_stopwords(search_service) -> None:
    manhwa = await search_service.list(query="манхва", limit=10)
    assert manhwa.total >= 5
    assert all(
        item.content_type == "манхва" or item.source_id in {"solo-leveling"}
        for item in manhwa.items
    )

    genre_alias = await search_service.list(query="боевик", genre=None, limit=10)
    assert genre_alias.total >= 5

    # "читать" describes the action, not the title; it must not hide results.
    with_stopword = await top_ids(search_service, "читать человек бензопила")
    without_stopword = await top_ids(search_service, "человек бензопила")
    assert with_stopword == without_stopword


@pytest.mark.asyncio
async def test_empty_punctuation_long_and_thin_queries(search_service) -> None:
    empty = await search_service.list(query="", limit=5)
    assert empty.total == len(TITLES)

    whitespace = await search_service.list(query="   ", limit=5)
    assert whitespace.total == len(TITLES)

    punctuation = await search_service.list(query="!!! ??? ---", limit=5)
    assert punctuation.total == 0
    assert punctuation.items == []

    long_query = "человек бензопила " + ("оченьдлинныйзапрос " * 500)
    result = await search_service.list(query=long_query, limit=5)
    # The query is clamped to 200 characters; the meaningful prefix still
    # matches, and the endpoint must not fail or return an unbounded document.
    assert result.total <= 1
    if result.items:
        assert result.items[0].source_id == "chainsaw-man"

    thin = await search_service.list(query="ч", limit=5)
    assert thin.total > 0


@pytest.mark.asyncio
async def test_pagination_is_stable(search_service) -> None:
    first = await search_service.list(query="манхва", limit=3, page=1)
    second = await search_service.list(query="манхва", limit=3, page=2)
    assert first.total == second.total
    assert len(first.items) == 3
    assert {item.id for item in first.items}.isdisjoint({item.id for item in second.items})
    assert first.has_next is True


@pytest.mark.asyncio
async def test_suggestions_are_ranked_local_and_honor_limit(search_service) -> None:
    suggestions = await search_service.suggest("чензо мен", limit=4)
    assert suggestions.items
    assert suggestions.items[0].id is not None
    assert suggestions.items[0].title == "Человек-бензопила"
    assert len(suggestions.items) <= 4

    short = await search_service.suggest("!!!", limit=4)
    assert short.items == []


@pytest.mark.asyncio
async def test_suggestions_do_not_call_parser(search_service) -> None:
    # ExplodingParser raises on any call; reaching this assertion proves that
    # neither search nor suggestions used the upstream client.
    suggestions = await asyncio.gather(
        search_service.suggest("челов", limit=5),
        search_service.suggest("solo lev", limit=5),
        search_service.suggest("овергир", limit=5),
    )
    assert all(item.items for item in suggestions)


@pytest.mark.asyncio
async def test_search_falls_back_to_like_without_fts(tmp_path: Path) -> None:
    db_path = tmp_path / "no-fts.db"
    settings = CatalogSettings(
        service_name="catalog-no-fts-test",
        catalog_database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
    )
    engine = create_engine(settings.catalog_dsn)
    await create_all(engine)
    await ensure_runtime_schema(engine)
    service = CatalogService(settings, create_session_factory(engine), ExplodingParser())  # type: ignore[arg-type]
    await service.import_detail(detail_from_spec(TITLES[0]))
    async with engine.begin() as connection:
        await connection.execute(text("DROP TABLE manga_search_fts"))
    result = await service.list(query="чензо мен")
    assert result.items and result.items[0].source_id == "chainsaw-man"
    await engine.dispose()


@pytest.mark.asyncio
async def test_runtime_migration_adds_search_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy-search.db"
    settings = CatalogSettings(
        service_name="catalog-legacy-search-test",
        catalog_database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
    )
    engine = create_engine(settings.catalog_dsn)
    await create_all(engine)
    await ensure_runtime_schema(engine)
    service = CatalogService(settings, create_session_factory(engine), ExplodingParser())  # type: ignore[arg-type]
    await service.import_detail(detail_from_spec(TITLES[0]))

    async with engine.begin() as connection:
        await connection.execute(text("DROP TABLE manga_search_fts"))
        await connection.execute(text("DROP INDEX IF EXISTS ix_manga_search_title"))
        await connection.execute(text("DROP INDEX IF EXISTS ix_manga_search_pending"))
        for column in (
            "search_title",
            "search_alt",
            "search_author",
            "search_names",
            "search_meta",
            "search_description",
            "search_blob",
            "search_doc_version",
            "search_indexed",
            "authors",
            "artists",
        ):
            await connection.execute(text(f"ALTER TABLE manga DROP COLUMN {column}"))

    await ensure_runtime_schema(engine)
    await bootstrap_search_index(service.session_factory)
    worker = SearchBackfillWorker(
        service.session_factory,
        BackfillConfig(batch_size=10, yield_seconds=0.0),
        owner="column-test",
    )
    await worker.run()
    result = await service.list(query="человек бензопила")
    assert result.items and result.items[0].source_id == "chainsaw-man"
    await engine.dispose()


def test_author_metadata_is_indexed_when_present() -> None:
    fields = build_search_fields(
        title="Пример",
        title_en=None,
        title_alt=None,
        genres=[],
        content_type=None,
        description=None,
        metadata={"authors": ["Иванов"], "artists": ["Петров"]},
    )
    assert "иванов" in fields["search_author"]
    assert "петров" in fields["search_author"]
    assert "иванов" in fields["search_blob"]
    assert "иванов" not in fields["search_alt"]


def test_explicit_people_and_confusable_skeleton() -> None:
    fields = build_search_fields(
        title="Человек-бензопила",
        title_en="Chainsaw Man",
        title_alt=None,
        genres=["Экшен"],
        content_type="манга",
        description=None,
        authors=["Тацуки Фудзимото"],
        artists=["Тацуки Фудзимото"],
    )
    assert "фудзимото" in fields["search_author"]
    # The confusable skeleton collapses з/с/ц and ч/ц, so a "чензо" query can
    # reach the document through the same candidate term as "ченсо".
    assert "цинс" in fields["search_alt"]
    assert "chns" in fields["search_alt"]


@pytest.mark.asyncio
async def test_backfill_copies_metadata_people_into_columns(search_service) -> None:
    async with search_service.session_factory() as session:
        await session.execute(
            text(
                "UPDATE manga SET metadata = :metadata, search_indexed = 0, "
                "search_doc_version = 0, authors = '[]', artists = '[]' "
                "WHERE source_id = 'naruto'"
            ),
            {"metadata": '{"authors": ["Масаси Кисимото"], "artists": ["Масаси Кисимото"]}'},
        )
        await session.commit()

    worker = SearchBackfillWorker(
        search_service.session_factory,
        BackfillConfig(batch_size=10, yield_seconds=0.0),
        owner="people-backfill-test",
    )
    await worker.run()

    result = await search_service.list(query="Кисимото", limit=3)
    assert result.items
    assert result.items[0].source_id == "naruto"
    assert result.items[0].authors == ["Масаси Кисимото"]
    assert result.items[0].artists == ["Масаси Кисимото"]


@pytest.mark.asyncio
async def test_sqlite_fts_mirror_is_populated(search_service) -> None:
    async with search_service.session_factory() as session:
        assert await fts_available(session)
        indexed = await session.scalar(text("SELECT count(*) FROM manga_search_fts"))
        rows = await session.scalar(text("SELECT count(*) FROM manga"))
        assert indexed == rows == len(TITLES)


def test_postgres_like_sql_compiles() -> None:
    from sqlalchemy.dialects import postgresql

    query = analyze_query("чензо мен")
    terms = expansion_terms(query, dialect="postgresql")
    assert terms
    # The PostgreSQL LIKE pre-filter must contain the same confusable/skeleton
    # candidates as SQLite FTS; otherwise Chainsaw Man never reaches the
    # Python ranker in production.
    assert "chns" in terms or "цинс" in terms
    statement = select(Manga.id).where(
        or_(*[Manga.search_blob.contains(term, autoescape=True) for term in terms])
    )
    compiled = str(statement.compile(dialect=postgresql.dialect()))
    assert "search_blob LIKE" in compiled
    assert "ESCAPE" in compiled
