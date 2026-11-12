from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from manga_common.db import create_all, create_engine, create_session_factory, ping
from manga_common.service import add_ready_check, create_service_app
from sqlalchemy.engine import make_url

from .api import router
from .config import CommentsSettings
from .push import NotifierPushDispatcher
from .service import CommentsService

logger = logging.getLogger(__name__)


def _ensure_sqlite_directory(dsn: str) -> None:
    if not dsn.startswith("sqlite"):
        return
    database = make_url(dsn).database
    if not database or database == ":memory:":
        return
    path = Path(database)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)


def create_app(settings: CommentsSettings | None = None) -> FastAPI:
    settings = settings or CommentsSettings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.is_production and (
            not settings.internal_token
            or settings.internal_token.startswith(("dev-", "change-me"))
        ):
            raise RuntimeError("INTERNAL_TOKEN must be changed in production")

        _ensure_sqlite_directory(settings.comments_dsn)
        engine = create_engine(settings.comments_dsn, echo=settings.debug)
        session_factory = create_session_factory(engine)
        await create_all(engine)
        app.state.engine = engine
        app.state.session_factory = session_factory
        dispatcher = (
            NotifierPushDispatcher(settings)
            if settings.chapter_notifications_push_enabled
            else None
        )
        app.state.service = CommentsService(settings, session_factory, dispatcher)

        async def db_ready() -> bool:
            return await ping(engine)

        add_ready_check(app, "database", db_ready)
        logger.info("comments service ready")
        try:
            yield
        finally:
            if dispatcher is not None:
                await dispatcher.close()
            await engine.dispose()

    app = create_service_app(
        settings=settings,
        title="MangaPoisk Reborn — Comments",
        description=(
            "Title comments, one-level replies, likes, reports and moderation "
            "for MangaPoisk Reborn."
        ),
    )
    app.router.lifespan_context = lifespan
    app.include_router(router)
    return app


settings = CommentsSettings()
app = create_app(settings)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.debug)
