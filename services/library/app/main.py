from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from manga_common.db import create_all, create_engine, create_session_factory, ping
from manga_common.service import add_ready_check, create_service_app

from .api import router
from .config import LibrarySettings
from .migrations import ensure_runtime_schema
from .profiles import ProfileService
from .service import LibraryService

logger = logging.getLogger(__name__)
settings = LibrarySettings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate_production_secrets()
    engine = create_engine(settings.library_dsn, echo=settings.debug)
    session_factory = create_session_factory(engine)
    await create_all(engine)
    await ensure_runtime_schema(engine)
    if settings.yandex_oauth_partial:
        logger.warning(
            "Yandex OAuth is partially configured; set all of "
            "YANDEX_CLIENT_ID, YANDEX_CLIENT_SECRET and YANDEX_REDIRECT_URI"
        )
    service = LibraryService(settings, session_factory)
    profiles = ProfileService(settings, session_factory)
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.service = service
    app.state.profiles = profiles

    async def db_ready() -> bool:
        return await ping(engine)

    add_ready_check(app, "database", db_ready)
    logger.info("library service ready")
    try:
        yield
    finally:
        await engine.dispose()


app = create_service_app(
    settings=settings,
    title="MangaPoisk Reborn — Library",
    description="Accounts, JWT, bookmarks, reading progress and reader settings.",
)
app.router.lifespan_context = lifespan
app.include_router(router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.debug)
