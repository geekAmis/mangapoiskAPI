from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from manga_common.db import create_engine, create_session_factory, ping
from manga_common.service import add_ready_check, create_service_app
from sqlalchemy import text

from .api import router
from .config import CatalogSettings
from .migrations import ensure_runtime_schema
from .observability import (
    install_slow_query_logging,
    install_sqlite_optimize_on_close,
)
from .parser_client import ParserClient
from .search_backfill import (
    BackfillConfig,
    SearchBackfillWorker,
    bootstrap_search_index,
)
from .service import CatalogService

logger = logging.getLogger(__name__)
settings = CatalogSettings()


async def _optimize_planner_stats(engine) -> float:  # type: ignore[no-untyped-def]
    """Bounded SQLite stats refresh; never a full blocking ANALYZE."""

    started = time.perf_counter()
    async with engine.connect() as connection:
        await connection.execute(text("PRAGMA analysis_limit=400"))
        await connection.execute(text("PRAGMA optimize"))
        await connection.commit()
    elapsed_ms = (time.perf_counter() - started) * 1000
    logger.info("catalogue planner stats optimized in %.0fms", elapsed_ms)
    return elapsed_ms


async def _planner_stats_loop(engine, interval_seconds: int) -> None:  # type: ignore[no-untyped-def]
    interval = max(60, int(interval_seconds))
    while True:
        await asyncio.sleep(interval)
        try:
            await _optimize_planner_stats(engine)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("catalogue planner stats refresh failed", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate_production_secrets()
    started = time.perf_counter()
    engine = create_engine(settings.catalog_dsn, echo=settings.debug)
    install_slow_query_logging(engine, threshold_ms=settings.slow_query_ms)
    install_sqlite_optimize_on_close(engine)
    session_factory = create_session_factory(engine)
    await ensure_runtime_schema(engine)
    schema_elapsed = time.perf_counter() - started
    try:
        bootstrap = await bootstrap_search_index(
            session_factory, batch_size=settings.search_backfill_batch_size
        )
    except Exception:
        # A broken FTS mirror must not block health: the worker and the legacy
        # SQL fallback still make progress and search degrades gracefully.
        logger.exception("search bootstrap failed; continuing with legacy fallback")
        bootstrap = {"pending": -1}
    parser = ParserClient(settings)
    service = CatalogService(settings, session_factory, parser)
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.service = service
    app.state.parser = parser
    app.state.search_backfill = None
    app.state.search_backfill_task = None
    logger.info(
        "catalog startup ready in %.2fs (schema %.2fs, bootstrap %s)",
        time.perf_counter() - started,
        schema_elapsed,
        bootstrap,
    )
    if settings.search_backfill_enabled:
        worker = SearchBackfillWorker(
            session_factory,
            BackfillConfig(
                batch_size=settings.search_backfill_batch_size,
                lease_seconds=settings.search_backfill_lease_seconds,
                yield_seconds=settings.search_backfill_yield_seconds,
                max_retries=settings.search_backfill_max_retries,
            ),
        )
        app.state.search_backfill = worker
        app.state.search_backfill_task = asyncio.create_task(worker.run())
        if bootstrap.get("pending", -1) != 0:
            logger.info("search backfill started in background")
        else:
            logger.info("search backfill already complete; maintenance worker started")
    elif bootstrap:
        logger.info("search backfill disabled by configuration")

    stats_task: asyncio.Task[None] | None = None
    if settings.stats_optimize_enabled and engine.dialect.name == "sqlite":
        stats_task = asyncio.create_task(
            _planner_stats_loop(engine, settings.stats_optimize_interval_seconds)
        )

    async def db_ready() -> bool:
        return await ping(engine)

    add_ready_check(app, "database", db_ready)

    async def sync_sources() -> None:
        try:
            sources = await asyncio.wait_for(parser.sources(), timeout=10.0)
            await service.sync_sources(sources)
            logger.info("synchronised %s sources from parser", len(sources))
        except Exception as exc:
            logger.warning("could not synchronise sources at startup: %s", exc)

    sync_task = asyncio.create_task(sync_sources())
    try:
        yield
    finally:
        sync_task.cancel()
        await asyncio.gather(sync_task, return_exceptions=True)
        backfill_task = getattr(app.state, "search_backfill_task", None)
        if backfill_task is not None:
            backfill_task.cancel()
            await asyncio.gather(backfill_task, return_exceptions=True)
        if stats_task is not None:
            stats_task.cancel()
            await asyncio.gather(stats_task, return_exceptions=True)
        if engine.dialect.name == "sqlite":
            try:
                await asyncio.wait_for(_optimize_planner_stats(engine), timeout=5.0)
            except Exception:
                logger.debug("final planner stats refresh skipped", exc_info=True)
        await parser.close()
        await engine.dispose()


app = create_service_app(
    settings=settings,
    title="MangaPoisk Reborn — Catalog",
    description="PostgreSQL catalogue, search and import service.",
)
app.router.lifespan_context = lifespan
app.include_router(router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.debug)
