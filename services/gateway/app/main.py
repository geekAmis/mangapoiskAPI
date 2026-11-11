from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from manga_common.service import add_ready_check, create_service_app

from .api import _apply_registry, router
from .clients import CatalogClient, ControlClient, LibraryClient, MediaClient, ParserClient
from .config import GatewaySettings
from .middleware import RateLimitMiddleware

logger = logging.getLogger(__name__)
settings = GatewaySettings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate_production_secrets()
    catalog = CatalogClient(settings, settings.catalog_url)
    parser = ParserClient(settings, settings.parser_url)
    library = LibraryClient(settings, settings.library_url)
    media = MediaClient(settings, settings.media_url)
    control = ControlClient(settings, settings.control_url)
    app.state.catalog = catalog
    app.state.parser = parser
    app.state.library = library
    app.state.media = media
    app.state.control = control

    async def health_check(client) -> bool:  # type: ignore[no-untyped-def]
        try:
            response = await client.client.get("/health", timeout=3.0)
            return response.status_code == 200
        except Exception:
            return False

    add_ready_check(app, "catalog", lambda: health_check(catalog))
    add_ready_check(app, "parser", lambda: health_check(parser))
    add_ready_check(app, "library", lambda: health_check(library))
    add_ready_check(app, "media", lambda: health_check(media))

    async def registry_sync() -> None:
        # The control service is optional: without it the gateway keeps the
        # static URLs from .env.  When it is present, a healthy server with the
        # lowest priority number wins; the main 83 host can be a fallback.
        while True:
            try:
                registry = await control.registry()
                await _apply_registry(app, registry)
            except Exception as exc:
                logger.debug("registry sync skipped: %s", exc)
            await asyncio.sleep(20)

    sync_task = asyncio.create_task(registry_sync())
    logger.info("gateway ready")
    try:
        yield
    finally:
        sync_task.cancel()
        await asyncio.gather(sync_task, return_exceptions=True)
        await asyncio.gather(
            catalog.close(), parser.close(), library.close(), media.close(), control.close(),
            return_exceptions=True,
        )


app = create_service_app(
    settings=settings,
    title="MangaPoisk Reborn — Public API",
    description="Public API v1 for web, Android and third-party clients.",
)
app.router.lifespan_context = lifespan
app.add_middleware(
    RateLimitMiddleware,
    default_limit=settings.gateway_rate_limit_per_minute,
    search_limit=settings.gateway_search_limit_per_minute,
    import_limit=settings.gateway_import_limit_per_minute,
)
app.include_router(router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.debug)
