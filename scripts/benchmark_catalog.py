"""Benchmark the catalogue list endpoint on a production-sized SQLite fixture.

The fixture has 100k manga rows, 20k canonical groups and (optionally) ~1.7M
chapter rows.  It measures the internal catalog endpoint and the public gateway
route, both idle and while a writer continuously refreshes card rows.

Examples:
    .venv/Scripts/python scripts/benchmark_catalog.py --titles 100000
    .venv/Scripts/python scripts/benchmark_catalog.py --titles 100000 \
        --chapters-per-title 17 --runs 30 \
        --json-out docs/benchmarks/catalog-list-100k.json

The default creates a throwaway SQLite database; nothing is written to the
repository database.  ``--database-url`` can point at PostgreSQL, but the
production deployment this issue targets is SQLite.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import statistics
import tempfile
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from manga_common.db import create_all, create_engine, create_session_factory
from manga_common.security import require_internal_token
from services.catalog.app.api import get_service
from services.catalog.app.api import router as catalog_router
from services.catalog.app.config import CatalogSettings
from services.catalog.app.migrations import ensure_runtime_schema
from services.catalog.app.models import CatalogGroup, CatalogSourceGroup, Chapter, Manga
from services.catalog.app.normalization import genres_key, status_key
from services.catalog.app.repository import compute_group_key
from services.catalog.app.service import CatalogService
from services.gateway.app.api import router as gateway_router
from services.gateway.app.clients import CatalogClient
from services.gateway.app.config import GatewaySettings
from sqlalchemy import event, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine

GENRES = [["фэнтези", "приключения"], ["ужасы", "фэнтези"], ["романтика", "драма"]]
STATUSES = ["ongoing", "completed", "announced"]
BASE_TITLES = [
    "Клинок, рассекающий демонов",
    "Магическая битва",
    "Человек-бензопила",
    "Соло Левелинг",
    "Поднятие уровня в одиночку",
]


def _configure_sqlite(engine: AsyncEngine) -> None:
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
            "busy_timeout=15000",
        ):
            cursor.execute(f"PRAGMA {pragma}")
        cursor.close()


async def _seed(
    engine: AsyncEngine,
    *,
    titles: int,
    groups: int,
    chapters_per_title: int,
) -> dict[str, int]:
    """Bulk-insert a realistic catalogue without the per-row import path."""

    groups = max(1, min(groups, titles))
    variants = max(1, titles // groups)
    now = datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    chapter_rows = 0
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO sources (code, name, base_url, language, enabled, "
                "requires_cookies, capabilities) VALUES "
                "('mangapoisk','MangaPoisk','https://example','ru',1,0,'{}')"
            )
        )

    async with create_session_factory(engine)() as session:
        manga_table = Manga.__table__
        for index in range(titles):
            group = index % groups
            variant = index // groups
            base = BASE_TITLES[group % len(BASE_TITLES)]
            title = f"{base} {group}"
            if variant:
                title += f" (вариант {variant})"
            # Every fifth variant is a summary-only row: it advertises chapters
            # but has no chapter rows.  These must never become empty cards.
            visible = variants == 1 or variant != variants - 1
            source_id = f"bench-{index}"
            genres = GENRES[group % len(GENRES)]
            rating = round(6.0 + (group % 40) / 10, 1)
            rows.append(
                {
                    "id": uuid.uuid4(),
                    "source": "mangapoisk",
                    "source_id": source_id,
                    "slug": source_id,
                    "title": title,
                    "title_en": f"Benchmark Title {group}",
                    "title_alt": None,
                    "description": "Описание тайтла для нагрузочного теста.",
                    "year": 2015 + group % 10,
                    "status": STATUSES[group % len(STATUSES)],
                    "status_key": status_key(STATUSES[group % len(STATUSES)]),
                    "content_type": "манга",
                    "rating": rating,
                    "rating_count": 100 + (group * 37) % 50_000,
                    "poster_url": f"https://cdn.example/{source_id}.jpg",
                    "adult": False,
                    "genres": genres,
                    "genres_key": genres_key(genres),
                    "search_title": "",
                    "search_alt": "",
                    "search_names": "",
                    "search_meta": "",
                    "search_description": "",
                    "search_blob": "",
                    "search_indexed": False,
                    "url": f"https://example/manga/{source_id}",
                    "group_key": compute_group_key(title) or f"manga-{index}",
                    "chapters_count": chapters_per_title if visible else 25,
                    "has_chapters": False,
                    "last_chapter_at": now - timedelta(days=group % 400),
                    "created_at": now - timedelta(days=group % 900),
                    "updated_at": now - timedelta(days=group % 200),
                    "enrichment_attempts": 0,
                    "metadata": {},
                }
            )
            if visible:
                chapter_rows += chapters_per_title
            if len(rows) >= 5_000:
                await session.execute(manga_table.insert(), rows)
                rows.clear()
        if rows:
            await session.execute(manga_table.insert(), rows)
        await session.commit()

        # Chapter rows are inserted in bounded chunks; 1.7M rows are expected
        # for the production-shaped run and must not sit in one Python list.
        chapter_table = Chapter.__table__
        buffer: list[dict[str, Any]] = []
        inserted = 0
        async with engine.connect() as read_connection:
            ids = (
                await read_connection.execute(
                    select(Manga.id, Manga.source_id, Manga.has_chapters)
                    .where(Manga.has_chapters.is_(False))
                    .order_by(Manga.id)
                )
            ).all()
        # The seed marks every row as hidden; visible variants are the first
        # ``variants - 1`` rows of each group, so derive them from source_id.
        visible_ids = [
            row[0]
            for row in ids
            if variants == 1
            or int(str(row[1]).rsplit("-", 1)[-1]) // groups != variants - 1
        ]
        for manga_id in visible_ids:
            for number in range(1, chapters_per_title + 1):
                buffer.append(
                    {
                        "id": uuid.uuid4(),
                        "manga_id": manga_id,
                        "source": "mangapoisk",
                        "source_id": f"{manga_id.hex}-{number}",
                        "volume": None,
                        "number": str(number),
                        "title": f"Глава {number}",
                        "translator": None,
                        "published_at": now - timedelta(days=number % 100),
                        "page_count": 16,
                        "pages": None,
                        "pages_cached_at": None,
                        "url": None,
                        "is_external": False,
                        "is_horizontal": False,
                    }
                )
                inserted += 1
                if len(buffer) >= 5_000:
                    await session.execute(chapter_table.insert(), buffer)
                    buffer.clear()
        if buffer:
            await session.execute(chapter_table.insert(), buffer)
        await session.commit()
    return {"manga": titles, "groups": groups, "chapters": chapter_rows}


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def _summary(values: list[float]) -> dict[str, float | int]:
    return {
        "samples": len(values),
        "p50_ms": round(_percentile(values, 0.50), 2),
        "p95_ms": round(_percentile(values, 0.95), 2),
        "mean_ms": round(statistics.fmean(values), 2) if values else 0.0,
        "max_ms": round(max(values), 2) if values else 0.0,
    }


def _catalog_app(service: CatalogService) -> FastAPI:
    app = FastAPI()
    app.include_router(catalog_router)
    app.dependency_overrides[require_internal_token] = lambda: None
    app.dependency_overrides[get_service] = lambda: service
    return app


def _gateway_app(catalog_transport: httpx.AsyncBaseTransport) -> tuple[FastAPI, CatalogClient]:
    settings = GatewaySettings(
        service_name="gateway-benchmark",
        environment="test",
        catalog_url="http://catalog",
    )
    app = FastAPI()
    app.include_router(gateway_router)
    app.state.settings = settings
    client = CatalogClient(settings, "http://catalog")
    client.client = httpx.AsyncClient(
        transport=catalog_transport,
        base_url="http://catalog",
        headers={"X-Internal-Token": settings.internal_token},
    )
    app.state.catalog = client
    app.state.parser = None
    app.state.library = None
    app.state.media = None
    app.state.control = None
    app.state.comments = None
    app.state.notifier = None
    app.state.pool = None
    return app, client


async def _measure(
    client: httpx.AsyncClient,
    path: str,
    params: dict[str, Any],
    *,
    runs: int,
) -> list[float]:
    times: list[float] = []
    for _ in range(runs):
        started = time.perf_counter()
        response = await client.get(path, params=params)
        times.append((time.perf_counter() - started) * 1000)
        response.raise_for_status()
    return times


async def _legacy_queries(engine: AsyncEngine) -> dict[str, float]:
    """Time the pre-#68 count/list shapes for a before/after comparison."""

    async with engine.connect() as connection:
        started = time.perf_counter()
        count = (
            await connection.execute(
                text(
                    "SELECT count(*) FROM ("
                    "SELECT group_key FROM manga "
                    "WHERE chapters_count > 0 AND EXISTS "
                    "(SELECT 1 FROM chapters WHERE chapters.manga_id = manga.id) "
                    "GROUP BY group_key)"
                )
            )
        ).scalar()
        count_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        list_rows = (
            await connection.execute(
                text(
                    "SELECT id FROM ("
                    "SELECT id, rating_count, rating, updated_at, row_number() OVER ("
                    "PARTITION BY coalesce(nullif(group_key,''), id) "
                    "ORDER BY chapters_count DESC, rating DESC, updated_at DESC) AS rn "
                    "FROM manga WHERE chapters_count > 0 AND EXISTS "
                    "(SELECT 1 FROM chapters WHERE chapters.manga_id = manga.id)) "
                    "WHERE rn = 1 ORDER BY rating_count DESC, rating DESC, "
                    "updated_at DESC LIMIT 20"
                )
            )
        ).all()
        list_ms = (time.perf_counter() - started) * 1000
    return {"count_ms": round(count_ms, 2), "count": int(count or 0),
            "list_ms": round(list_ms, 2), "list_rows": len(list_rows)}


async def _explain(engine: AsyncEngine) -> dict[str, str]:
    statements = {
        "count": "SELECT count(*) FROM catalog_groups",
        "popular": (
            "SELECT manga_id FROM catalog_groups ORDER BY rating_count DESC, "
            "rating DESC, updated_at DESC, group_key DESC LIMIT 20"
        ),
        "genre": (
            "SELECT manga_id FROM catalog_groups WHERE genres_key LIKE '%|fantasy|%' "
            "ORDER BY rating_count DESC, rating DESC, updated_at DESC, "
            "group_key DESC LIMIT 20"
        ),
        "title": "SELECT manga_id FROM catalog_groups ORDER BY title ASC, group_key ASC LIMIT 20",
        "manga_visible_group": (
            "SELECT id FROM manga WHERE has_chapters = 1 AND group_key = 'demo' "
            "ORDER BY chapters_count DESC, id ASC LIMIT 1"
        ),
    }
    result: dict[str, str] = {}
    async with engine.connect() as connection:
        for name, statement in statements.items():
            rows = (await connection.execute(text(f"EXPLAIN QUERY PLAN {statement}"))).all()
            result[name] = " | ".join(str(row[-1]) for row in rows)
    return result


async def _writer(
    factory, stop: asyncio.Event, errors: list[str]
) -> None:  # type: ignore[no-untyped-def]
    """Simulate crawler card refreshes while list requests are measured."""

    while not stop.is_set():
        try:
            async with factory() as session:
                # Real crawler writes touch both the manga variant and its
                # materialised card.  Pick a handful of random rows so the
                # writer never becomes a full-table scan itself.
                source_ids = (
                    await session.scalars(
                        select(Manga.source_id).order_by(func.random()).limit(5)
                    )
                ).all()
                group_keys = (
                    await session.scalars(
                        select(CatalogGroup.group_key).order_by(func.random()).limit(5)
                    )
                ).all()
                source_keys = (
                    await session.execute(
                        select(
                            CatalogSourceGroup.group_key, CatalogSourceGroup.source
                        )
                        .order_by(func.random())
                        .limit(5)
                    )
                ).all()
                if source_ids:
                    await session.execute(
                        update(Manga)
                        .where(Manga.source_id.in_(source_ids))
                        .values(
                            rating_count=random.randrange(0, 50_000),
                            updated_at=datetime.now(UTC),
                        )
                    )
                if group_keys:
                    await session.execute(
                        update(CatalogGroup)
                        .where(CatalogGroup.group_key.in_(group_keys))
                        .values(rating_count=random.randrange(0, 50_000))
                    )
                for group_key, source in source_keys:
                    await session.execute(
                        update(CatalogSourceGroup)
                        .where(
                            CatalogSourceGroup.group_key == group_key,
                            CatalogSourceGroup.source == source,
                        )
                        .values(rating_count=random.randrange(0, 50_000))
                    )
                await session.commit()
        except Exception as exc:  # pragma: no cover - timing depends on lock races
            errors.append(f"{type(exc).__name__}: {exc}")
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.02)


async def run_benchmark(
    *,
    titles: int,
    groups: int,
    chapters_per_title: int,
    runs: int,
    database_url: str | None,
    json_out: str | None,
) -> dict[str, Any]:
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if database_url:
        dsn = database_url
        db_path = None
    else:
        temp_dir = tempfile.TemporaryDirectory(prefix="mangapoisk-catalog-bench-")
        db_path = Path(temp_dir.name) / "benchmark.db"
        dsn = f"sqlite+aiosqlite:///{db_path.as_posix()}"

    settings = CatalogSettings(service_name="catalog-benchmark", catalog_database_url=dsn)
    engine = create_engine(settings.catalog_dsn)
    _configure_sqlite(engine)
    dialect = engine.dialect.name
    if database_url:
        await create_all(engine)
        await ensure_runtime_schema(engine)
        fixture = await _seed(
            engine, titles=titles, groups=groups, chapters_per_title=chapters_per_title
        )
    else:
        await create_all(engine)
        fixture = await _seed(
            engine, titles=titles, groups=groups, chapters_per_title=chapters_per_title
        )
    migration_started = time.perf_counter()
    await ensure_runtime_schema(engine)
    migration_ms = (time.perf_counter() - migration_started) * 1000
    restart_started = time.perf_counter()
    await ensure_runtime_schema(engine)
    restart_ms = (time.perf_counter() - restart_started) * 1000
    if dialect == "sqlite":
        async with engine.begin() as connection:
            await connection.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))

    factory = create_session_factory(engine)
    service = CatalogService(settings, factory, None)  # type: ignore[arg-type]
    catalog_app = _catalog_app(service)
    catalog_transport = httpx.ASGITransport(app=catalog_app)
    internal_client = httpx.AsyncClient(
        transport=catalog_transport, base_url="http://catalog"
    )
    gateway_app, gateway_catalog = _gateway_app(catalog_transport)
    gateway_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway_app), base_url="http://gateway"
    )

    scenarios: list[tuple[str, dict[str, Any]]] = [
        ("popular", {"sort": "popular", "limit": 20}),
        ("rating", {"sort": "rating", "limit": 20}),
        ("updated", {"sort": "updated", "limit": 20}),
        ("title", {"sort": "title", "limit": 20}),
        ("new", {"sort": "new", "limit": 20}),
        ("genre_fantasy", {"genre": "fantasy", "limit": 20}),
        ("genres_and", {"genres": "fantasy+horror", "limit": 20}),
        ("status", {"status": "ongoing", "limit": 20}),
        ("year", {"year": 2020, "limit": 20}),
        ("source", {"source": "mangapoisk", "limit": 20}),
        ("page_10", {"sort": "popular", "page": 10, "limit": 20}),
    ]
    # Warm-up: prepare SQL statements and page cache.
    for _name, params in scenarios:
        await internal_client.get("/internal/manga", params=params)
        await gateway_client.get("/api/v1/manga", params=params)

    internal: dict[str, Any] = {}
    public: dict[str, Any] = {}
    for name, params in scenarios:
        internal[name] = _summary(
            await _measure(internal_client, "/internal/manga", params, runs=runs)
        )
        public[name] = _summary(
            await _measure(gateway_client, "/api/v1/manga", params, runs=runs)
        )

    # Concurrent writer scenario.  Measure the same popular query while a
    # crawler-like writer keeps touching manga/catalog_groups.
    stop = asyncio.Event()
    write_errors: list[str] = []
    writer_task = asyncio.create_task(_writer(factory, stop, write_errors))
    concurrent_internal = await _measure(
        internal_client, "/internal/manga", {"sort": "popular", "limit": 20}, runs=runs
    )
    concurrent_public = await _measure(
        gateway_client, "/api/v1/manga", {"sort": "popular", "limit": 20}, runs=runs
    )
    stop.set()
    await asyncio.gather(writer_task, return_exceptions=True)

    legacy = await _legacy_queries(engine)
    explain = await _explain(engine)
    optimize_started = time.perf_counter()
    async with engine.connect() as connection:
        if dialect == "sqlite":
            await connection.execute(text("PRAGMA analysis_limit=400"))
            await connection.execute(text("PRAGMA optimize"))
            await connection.commit()
        else:
            await connection.execute(text("ANALYZE catalog_groups"))
            await connection.commit()
    optimize_ms = (time.perf_counter() - optimize_started) * 1000
    async with factory() as session:
        cards = int(
            (await session.scalar(select(func.count()).select_from(Manga))) or 0
        )
        catalog_cards = int(
            (
                await session.scalar(
                    text("SELECT count(*) FROM catalog_groups")
                )
            )
            or 0
        )
        source_cards = int(
            (
                await session.scalar(
                    text("SELECT count(*) FROM catalog_source_groups")
                )
            )
            or 0
        )
        empty_cards = int(
            (
                await session.scalar(
                    text(
                        "SELECT count(*) FROM catalog_groups c "
                        "WHERE NOT EXISTS (SELECT 1 FROM chapters ch "
                        "WHERE ch.manga_id = c.manga_id)"
                    )
                )
            )
            or 0
        )
        indexed = int(
            (
                await session.scalar(
                    text(
                        "SELECT count(*) FROM manga "
                        "WHERE has_chapters = 1"
                    )
                )
            )
            or 0
        )

    await internal_client.aclose()
    await gateway_client.aclose()
    await gateway_catalog.close()
    await engine.dispose()
    if temp_dir is not None:
        temp_dir.cleanup()

    report: dict[str, Any] = {
        "dialect": dialect,
        "database": database_url or "temporary-sqlite",
        "fixture": fixture,
        "migration_ms": round(migration_ms, 2),
        "restart_migration_ms": round(restart_ms, 2),
        "planner_optimize_ms": round(optimize_ms, 2),
        "catalog_cards": catalog_cards,
        "catalog_source_cards": source_cards,
        "manga_rows": cards,
        "has_chapters_rows": indexed,
        "empty_cards": empty_cards,
        "runs": runs,
        "internal": internal,
        "public": public,
        "concurrent_writer": {
            "internal_popular": _summary(concurrent_internal),
            "public_popular": _summary(concurrent_public),
            "write_errors": write_errors[:5],
            "write_error_count": len(write_errors),
        },
        "legacy_pre_68": legacy,
        "explain": explain,
    }
    if json_out:
        Path(json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(json_out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--titles", type=int, default=100_000)
    parser.add_argument("--groups", type=int, default=20_000)
    parser.add_argument("--chapters-per-title", type=int, default=1)
    parser.add_argument("--runs", type=int, default=20)
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
            groups=max(1, args.groups),
            chapters_per_title=max(1, args.chapters_per_title),
            runs=max(1, args.runs),
            database_url=args.database_url,
            json_out=args.json_out,
        )
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
