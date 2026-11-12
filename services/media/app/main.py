from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from manga_common.service import add_ready_check, create_service_app

from .api import router
from .archive import ArchiveManager
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
    archives = ArchiveManager(
        cache,
        db_path=settings.archive_db_path,
        archive_dir=settings.archive_root,
        threshold_bytes=settings.archive_db_threshold_bytes,
        max_bytes=settings.archive_max_bytes,
        prune_interval_seconds=settings.archive_prune_interval_seconds,
    )
    app.state.cache = cache
    app.state.exports = exports
    app.state.archives = archives

    async def storage_ready() -> bool:
        return settings.cache_root.exists() and settings.exports_root.exists()

    add_ready_check(app, "storage", storage_ready)
    add_ready_check(app, "archives", archives.ready)
    await archives.startup()
    await archives.prune()
    await cache.prune()
    await exports.cleanup()
    # Sweep even when no new archive/image is written: idle volumes would
    # otherwise stay above their caps until the next request.
    cache.start_periodic_prune()
    archives.start_periodic_prune()
    logger.info("media service ready")
    try:
        yield
    finally:
        await archives.close()
        await exports.close()
        await cache.close()


app = create_service_app(
    settings=settings,
    title="MangaPoisk Reborn — Media",
    description=(
        "Polite image cache, persistent chapter archive and CBZ/PDF/HTML offline export jobs."
    ),
)
app.router.lifespan_context = lifespan
app.include_router(router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.debug)
