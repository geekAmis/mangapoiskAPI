from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from manga_common.db import create_all, create_engine, create_session_factory, ping
from manga_common.service import add_ready_check, create_service_app

from .api import router
from .config import CatalogSettings
from .parser_client import ParserClient
from .service import CatalogService

logger = logging.getLogger(__name__)
settings = CatalogSettings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate_production_secrets()
    engine = create_engine(settings.catalog_dsn, echo=settings.debug)
    session_factory = create_session_factory(engine)
    await create_all(engine)
    parser = ParserClient(settings)
    service = CatalogService(settings, session_factory, parser)
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.service = service
    app.state.parser = parser

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
