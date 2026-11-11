from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from manga_common.service import add_ready_check, create_service_app

from .api import router
from .cache import MediaCache
from .config import MediaSettings
from .exporter import ExportManager

logger = logging.getLogger(__name__)
settings = MediaSettings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    cache = MediaCache(settings)
    exports = ExportManager(
        cache,
        settings.exports_root,
        max_pages=settings.max_export_pages,
        ttl_hours=settings.export_ttl_hours,
    )
    app.state.cache = cache
    app.state.exports = exports

    async def storage_ready() -> bool:
        return settings.cache_root.exists() and settings.exports_root.exists()

    add_ready_check(app, "storage", storage_ready)
    await exports.cleanup()
    logger.info("media service ready")
    try:
        yield
    finally:
        await exports.close()
        await cache.close()


app = create_service_app(
    settings=settings,
    title="MangaPoisk Reborn — Media",
    description="Polite image cache and CBZ/PDF/HTML offline export jobs.",
)
app.router.lifespan_context = lifespan
app.include_router(router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.debug)
