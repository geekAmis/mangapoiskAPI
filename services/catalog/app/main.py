from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from manga_common.db import create_engine, create_session_factory, ping
from manga_common.service import add_ready_check, create_service_app

from .api import router
from .config import CatalogSettings
from .discovery import seed_smart_collections
from .migrations import ensure_runtime_schema
from .parser_client import ParserClient
from .search_backfill import (
    BackfillConfig,
    SearchBackfillWorker,
    bootstrap_search_index,
)
from .service import CatalogService

logger = logging.getLogger(__name__)
settings = CatalogSettings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate_production_secrets()
    started = time.perf_counter()
    engine = create_engine(settings.catalog_dsn, echo=settings.debug)
    session_factory = create_session_factory(engine)
    await ensure_runtime_schema(engine)
    async with session_factory() as session:
        created = await seed_smart_collections(session)
        await session.commit()
    if created:
        logger.info("seeded %s discovery collections", created)
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
