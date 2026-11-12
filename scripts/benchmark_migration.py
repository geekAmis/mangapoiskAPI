"""Measure catalogue startup + background search backfill on SQLite.

The fixture simulates a v1.2 database that already has the search columns but
not ``search_indexed``: schema upgrade, legacy FTS bootstrap, partial-backfill
search and the full Python normalization are timed separately.

Examples:
    .venv/Scripts/python scripts/benchmark_migration.py --titles 5000
    .venv/Scripts/python scripts/benchmark_migration.py --titles 78275 \
        --json-out docs/benchmarks/migration-sqlite-78275.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from manga_common.db import create_engine, create_session_factory
from services.catalog.app.config import CatalogSettings
from services.catalog.app.migrations import ensure_runtime_schema
from services.catalog.app.repository import search_backfill_stats
from services.catalog.app.search_backfill import (
    BackfillConfig,
    SearchBackfillWorker,
    bootstrap_search_index,
)
from services.catalog.app.search_fts import fts_row_count
from services.catalog.app.service import CatalogService
from sqlalchemy import text

DEFAULT_TITLES = 78_275


async def _seed(path: Path, count: int) -> None:
    settings = CatalogSettings(
        service_name="catalog-migration-benchmark",
        catalog_database_url=f"sqlite+aiosqlite:///{path.as_posix()}",
    )
    engine = create_engine(settings.catalog_dsn)
    from manga_common.db import create_all
    from sqlalchemy import text as sql_text

    await create_all(engine)
    async with engine.begin() as connection:
        # Simulate the pre-fix deployment: search columns exist, the
        # search_indexed marker and its partial index do not.
        await connection.execute(sql_text("DROP INDEX IF EXISTS ix_manga_search_pending"))
        await connection.execute(sql_text("ALTER TABLE manga DROP COLUMN search_indexed"))
        await connection.execute(
            sql_text(
                "INSERT INTO sources (code, name, base_url, language, enabled, "
                "requires_cookies, capabilities) VALUES "
                "('mangapoisk','MangaPoisk','https://example','ru',1,0,'{}')"
            )
        )
        rows = []
        for index in range(count):
            suffix = "" if index < 36 else f" {index // 36 + 1}"
            rows.append(
                {
                    "id": uuid.uuid4().hex,
                    "source": "mangapoisk",
                    "source_id": f"bench-{index}",
                    "slug": f"bench-{index}",
                    "title": f"Человек-бензопила{suffix}",
                    "title_en": f"Chainsaw Man{suffix}",
                    "title_alt": f"Chainsaw Man / チェンソーマン{suffix}",
                    "description": (
                        "Дэндзи мечтает о нормальной жизни, но становится "
                        "гибридом с бензопилой."
                    ),
                    "year": 2018,
                    "status": "ongoing",
                    "content_type": "манга",
                    "rating": 8.9,
                    "rating_count": 45_000 + index,
                    "adult": 0,
                    "genres": json.dumps(["Экшен", "Ужасы"], ensure_ascii=False),
                    "metadata": "{}",
                    "search_title": "",
                    "search_alt": "",
                    "search_names": "",
                    "search_meta": "",
                    "search_description": "",
                    "search_blob": "",
                    "group_key": f"group-{index}",
                    "chapters_count": 100,
                    "enrichment_attempts": 0,
                }
            )
        statement = sql_text(
            "INSERT INTO manga (id, source, source_id, slug, title, title_en, "
            "title_alt, description, year, status, content_type, rating, "
            "rating_count, adult, genres, metadata, search_title, search_alt, "
            "search_names, search_meta, search_description, search_blob, "
            "group_key, chapters_count, enrichment_attempts) VALUES "
            "(:id,:source,:source_id,:slug,:title,:title_en,:title_alt,"
            ":description,:year,:status,:content_type,:rating,:rating_count,"
            ":adult,:genres,:metadata,:search_title,:search_alt,:search_names,"
            ":search_meta,:search_description,:search_blob,:group_key,"
            ":chapters_count,:enrichment_attempts)"
        )
        for start in range(0, len(rows), 5_000):
            await connection.execute(statement, rows[start : start + 5_000])
        chapter_rows = [
            {
                "id": uuid.uuid4().hex,
                "manga_id": row["id"],
                "source": "mangapoisk",
                "source_id": f"chapter-{index}",
                "number": "1",
                "title": "Глава 1",
                "page_count": 16,
            }
            for index, row in enumerate(rows)
        ]
        chapter_statement = sql_text(
            "INSERT INTO chapters (id, manga_id, source, source_id, number, "
            "title, page_count, is_external, is_horizontal) VALUES "
            "(:id,:manga_id,:source,:source_id,:number,:title,:page_count,0,0)"
        )
        for start in range(0, len(chapter_rows), 5_000):
            await connection.execute(
                chapter_statement, chapter_rows[start : start + 5_000]
            )
    await engine.dispose()


async def _search_probe(service: CatalogService, label: str) -> dict[str, Any]:
    started = time.perf_counter()
    result = await service.list(query="человек бензопила", limit=3)
    elapsed = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    suggestions = await service.suggest("чензо мен", limit=3)
    suggest_ms = (time.perf_counter() - started) * 1000
    return {
        "label": label,
        "search_ms": round(elapsed, 2),
        "suggest_ms": round(suggest_ms, 2),
        "search_total": result.total,
        "search_first": result.items[0].source_id if result.items else None,
        "suggest_first": suggestions.items[0].title if suggestions.items else None,
    }


async def run(
    *,
    titles: int,
    batch_size: int,
    json_out: str | None,
    keep_db: bool,
) -> dict[str, Any]:
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if keep_db:
        path = Path("data") / "migration-benchmark.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()
    else:
        temp_dir = tempfile.TemporaryDirectory(prefix="mangapoisk-migration-bench-")
        path = Path(temp_dir.name) / "benchmark.db"
    await _seed(path, titles)
    settings = CatalogSettings(
        service_name="catalog-migration-benchmark",
        catalog_database_url=f"sqlite+aiosqlite:///{path.as_posix()}",
    )
    engine = create_engine(settings.catalog_dsn)
    factory = create_session_factory(engine)

    started = time.perf_counter()
    await ensure_runtime_schema(engine)
    schema_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    bootstrap = await bootstrap_search_index(factory, batch_size=batch_size)
    bootstrap_ms = (time.perf_counter() - started) * 1000
    startup_ms = schema_ms + bootstrap_ms

    service = CatalogService(settings, factory, None)  # type: ignore[arg-type]
    before = await _search_probe(service, "after_startup")

    worker = SearchBackfillWorker(
        factory,
        BackfillConfig(batch_size=batch_size, yield_seconds=0.0),
        owner="migration-benchmark",
    )
    first_batch = await worker.step()
    after_first = await _search_probe(service, "after_first_batch")
    started = time.perf_counter()
    processed = await worker.backfill()
    backfill_seconds = time.perf_counter() - started
    remaining = await worker.backfill()
    await worker.backfill_group_keys()
    await worker.backfill_cover_group_keys()
    async with factory() as session:
        state = await search_backfill_stats(session)
        fts_count = await fts_row_count(session)
        indexed = int(
            (
                await session.execute(
                    text("SELECT count(*) FROM manga WHERE search_indexed = 1")
                )
            ).scalar()
            or 0
        )
    await engine.dispose()
    db_bytes = path.stat().st_size if path.exists() else 0
    report = {
        "dialect": "sqlite",
        "titles": titles,
        "batch_size": batch_size,
        "schema_ms": round(schema_ms, 2),
        "bootstrap_ms": round(bootstrap_ms, 2),
        "startup_ms": round(startup_ms, 2),
        "startup_under_10s": startup_ms < 10_000,
        "bootstrap": bootstrap,
        "first_batch_rows": first_batch,
        "search_before_normalization": before,
        "search_after_first_batch": after_first,
        "backfill_seconds": round(backfill_seconds, 2),
        "backfill_rows": processed,
        "throughput_rows_per_second": round(processed / backfill_seconds, 1)
        if backfill_seconds
        else None,
        "second_run_rows": remaining,
        "indexed_rows": indexed,
        "fts_rows": fts_count,
        "state": state.model_dump(mode="json") if state is not None else None,
        "database_bytes": db_bytes,
    }
    if json_out:
        Path(json_out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if temp_dir is not None:
        temp_dir.cleanup()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--titles", type=int, default=DEFAULT_TITLES)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--json-out", default=None)
    parser.add_argument("--keep-db", action="store_true")
    args = parser.parse_args()
    report = asyncio.run(
        run(
            titles=max(1, args.titles),
            batch_size=max(1, args.batch_size),
            json_out=args.json_out,
            keep_db=args.keep_db,
        )
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
