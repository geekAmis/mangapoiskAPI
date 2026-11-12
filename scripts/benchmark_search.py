"""Local search benchmark for the catalogue relevance engine.

Examples:
    .venv/Scripts/python scripts/benchmark_search.py
    .venv/Scripts/python scripts/benchmark_search.py --titles 20000 --runs 7
    BENCHMARK_DATABASE_URL=postgresql+asyncpg://... \
        .venv/Scripts/python scripts/benchmark_search.py --database-url "$BENCHMARK_DATABASE_URL"

The default creates a throwaway SQLite database with a realistic fixture set.
Nothing is written to the repository database.  PostgreSQL mode is optional and
uses the same runtime migration (including pg_trgm indexes) as the service.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import tempfile
import time
from pathlib import Path

from manga_common.db import create_all, create_engine, create_session_factory
from services.catalog.app.config import CatalogSettings
from services.catalog.app.migrations import ensure_runtime_schema
from services.catalog.app.models import Chapter, Manga
from services.catalog.app.repository import compute_group_key, ensure_source
from services.catalog.app.search_fts import rebuild_search_fts
from services.catalog.app.service import CatalogService
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from tests.catalog.relevance_cases import RELEVANCE_CASES
from tests.fixtures.search_titles import TITLES


def _configure_sqlite(engine: AsyncEngine) -> None:
    """Warm, low-fsync SQLite settings for repeatable local measurements."""

    if engine.dialect.name != "sqlite":
        return

    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragmas(dbapi_connection, _record):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        for pragma in (
            "journal_mode=WAL",
            "synchronous=NORMAL",
            "temp_store=MEMORY",
            "cache_size=-65536",
            "mmap_size=268435456",
        ):
            cursor.execute(f"PRAGMA {pragma}")
        cursor.close()


def _sanitize_dsn(dsn: str) -> str:
    if "://" not in dsn:
        return dsn
    scheme, rest = dsn.split("://", 1)
    if "@" in rest:
        rest = rest.rsplit("@", 1)[1]
    return f"{scheme}://{rest}"


async def seed_sqlite(path: Path, count: int) -> None:
    settings = CatalogSettings(
        service_name="catalog-benchmark",
        catalog_database_url=f"sqlite+aiosqlite:///{path.as_posix()}",
    )
    engine = create_engine(settings.catalog_dsn)
    _configure_sqlite(engine)
    await create_all(engine)
    session_factory = create_session_factory(engine)
    async with session_factory() as session:
        await ensure_source(session, "mangapoisk", "MangaPoisk")
        await _seed_rows(session, count)
    await ensure_runtime_schema(engine)
    async with session_factory() as session:
        # Direct ORM seeding bypasses the service upsert path, so populate the
        # FTS mirror explicitly before measuring search latency.
        await rebuild_search_fts(session)
        await session.commit()
    async with engine.begin() as connection:
        await connection.execute(text("ANALYZE"))
        await connection.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
    await engine.dispose()


async def _seed_rows(session: AsyncSession, count: int) -> None:
    base_count = len(TITLES)
    mangas: list[Manga] = []
    for index in range(count):
        spec = TITLES[index % base_count]
        generation = index // base_count
        suffix = "" if generation == 0 else f" {generation + 1}"
        title = f"{spec.title}{suffix}"
        source_id = f"{spec.slug}-{index}"
        manga = Manga(
            source="mangapoisk",
            source_id=source_id,
            slug=source_id,
            title=title,
            title_en=f"{spec.title_en}{suffix}" if spec.title_en else None,
            title_alt=f"{spec.title_alt}{suffix}" if spec.title_alt else None,
            description=spec.description,
            year=spec.year,
            status=spec.status,
            content_type=spec.content_type,
            rating=spec.rating,
            rating_count=spec.rating_count + index,
            poster_url=f"https://cdn.example/{source_id}.jpg",
            genres=list(spec.genres),
            url=f"https://mangapoisk.me/manga/{source_id}",
            chapters_count=spec.chapters_count,
            group_key=compute_group_key(title),
        )
        manga.refresh_search_fields()
        mangas.append(manga)
    session.add_all(mangas)
    await session.flush()
    session.add_all(
        Chapter(
            manga_id=manga.id,
            source="mangapoisk",
            source_id=f"{manga.source_id}-1",
            number="1",
            title="Глава 1",
            page_count=16,
        )
        for manga in mangas
    )
    await session.commit()


async def _async_size(engine: AsyncEngine, dialect: str) -> dict[str, int]:
    result: dict[str, int] = {}
    async with engine.connect() as connection:
        if dialect == "sqlite":
            page_count = int((await connection.execute(text("PRAGMA page_count"))).scalar() or 0)
            page_size = int((await connection.execute(text("PRAGMA page_size"))).scalar() or 0)
            result["database_bytes"] = page_count * page_size
            try:
                rows = (
                    await connection.execute(
                        text(
                            "SELECT name, SUM(pgsize) FROM dbstat "
                            "WHERE name LIKE 'ix_manga%' OR name LIKE 'manga_search_fts%' "
                            "GROUP BY name"
                        )
                    )
                ).all()
                result["index_bytes"] = sum(int(row[1] or 0) for row in rows)
            except Exception:
                # dbstat is optional in some SQLite builds.  Report the indexed
                # text size instead of inventing an index size.
                result["index_bytes"] = 0
                result["fts_text_bytes"] = int(
                    (
                        await connection.execute(
                            text("SELECT COALESCE(SUM(length(body)), 0) FROM manga_search_fts")
                        )
                    ).scalar()
                    or 0
                )
        else:
            result["database_bytes"] = int(
                (await connection.execute(text("SELECT pg_total_relation_size('manga')"))).scalar()
                or 0
            )
            result["index_bytes"] = int(
                (await connection.execute(text("SELECT pg_indexes_size('manga')"))).scalar() or 0
            )
    return result


async def run_benchmark(
    *, titles: int, runs: int, database_url: str | None, json_out: str | None
) -> dict[str, object]:
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if database_url:
        dsn = database_url
        db_path = None
    else:
        temp_dir = tempfile.TemporaryDirectory(prefix="mangapoisk-search-bench-")
        db_path = Path(temp_dir.name) / "benchmark.db"
        dsn = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        await seed_sqlite(db_path, titles)

    settings = CatalogSettings(service_name="catalog-benchmark", catalog_database_url=dsn)
    engine = create_engine(settings.catalog_dsn)
    _configure_sqlite(engine)
    dialect = engine.dialect.name
    if database_url:
        await create_all(engine)
        await ensure_runtime_schema(engine)
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            await ensure_source(session, "mangapoisk", "MangaPoisk")
            await _seed_rows(session, titles)
        await ensure_runtime_schema(engine)

    session_factory = create_session_factory(engine)
    service = CatalogService(settings, session_factory, None)  # type: ignore[arg-type]
    queries = [case.query for case in RELEVANCE_CASES]

    # Warm-up: page cache, SQL prepare plans and Python's transliteration caches.
    for query in queries[:6]:
        await service.list(query=query, limit=24)
    for query in queries[:6]:
        await service.suggest(query, limit=6)

    search_times: list[float] = []
    suggest_times: list[float] = []
    search_medians: list[float] = []
    suggest_medians: list[float] = []
    for query in queries:
        query_search: list[float] = []
        query_suggest: list[float] = []
        for _ in range(runs):
            started = time.perf_counter()
            await service.list(query=query, limit=24)
            query_search.append((time.perf_counter() - started) * 1000)
            started = time.perf_counter()
            await service.suggest(query, limit=6)
            query_suggest.append((time.perf_counter() - started) * 1000)
        search_times.extend(query_search)
        suggest_times.extend(query_suggest)
        search_medians.append(statistics.median(query_search))
        suggest_medians.append(statistics.median(query_suggest))

    def percentile(values: list[float], fraction: float) -> float:
        ordered = sorted(values)
        index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
        return ordered[index]

    sizes = await _async_size(engine, dialect)
    await engine.dispose()
    if temp_dir is not None:
        temp_dir.cleanup()

    report: dict[str, object] = {
        "dialect": dialect,
        "database": _sanitize_dsn(dsn),
        "titles": titles,
        "queries": len(queries),
        "runs": runs,
        "search": {
            "samples": len(search_times),
            "p50_ms": round(percentile(search_medians, 0.50), 2),
            "p95_ms": round(percentile(search_medians, 0.95), 2),
            "p95_sample_ms": round(percentile(search_times, 0.95), 2),
            "mean_ms": round(statistics.fmean(search_medians), 2),
            "max_ms": round(max(search_medians), 2),
        },
        "suggest": {
            "samples": len(suggest_times),
            "p50_ms": round(percentile(suggest_medians, 0.50), 2),
            "p95_ms": round(percentile(suggest_medians, 0.95), 2),
            "p95_sample_ms": round(percentile(suggest_times, 0.95), 2),
            "mean_ms": round(statistics.fmean(suggest_medians), 2),
            "max_ms": round(max(suggest_medians), 2),
        },
        "sizes": sizes,
    }
    if json_out:
        Path(json_out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--titles", type=int, default=5_000)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("BENCHMARK_DATABASE_URL"),
        help="Optional PostgreSQL DSN; by default a temporary SQLite database is used.",
    )
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args()
    report = asyncio.run(
        run_benchmark(
            titles=max(1, args.titles),
            runs=max(1, args.runs),
            database_url=args.database_url,
            json_out=args.json_out,
        )
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
