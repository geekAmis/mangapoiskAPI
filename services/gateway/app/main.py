from __future__ import annotations

import asyncio
import hashlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from manga_common.service import add_ready_check, create_service_app

from .api import _apply_registry, router
from .clients import CatalogClient, ControlClient, LibraryClient, MediaClient, ParserClient
from .comments_api import router as comments_router
from .comments_client import CommentsClient
from .config import GatewaySettings
from .middleware import RateLimitMiddleware
from .notifications_api import router as notifications_router
from .notifier_client import NotifierClient
from .retention import router as retention_router
from .routing import EndpointPool, reset_client_key, set_client_key
from .seo import router as seo_router
from .seo import warm_sitemap_cache

logger = logging.getLogger(__name__)
settings = GatewaySettings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate_production_secrets()
    pool = EndpointPool()
    catalog = CatalogClient(settings, settings.catalog_url, pool=pool)
    parser = ParserClient(settings, settings.parser_url, pool=pool)
    library = LibraryClient(settings, settings.library_url, pool=pool)
    media = MediaClient(settings, settings.media_url, pool=pool)
    control = ControlClient(settings, settings.control_url, pool=pool)
    comments = CommentsClient(settings, settings.comments_url, pool=pool)
    notifier = NotifierClient(settings, settings.notifier_url, pool=pool)
    app.state.pool = pool
    app.state.catalog = catalog
    app.state.parser = parser
    app.state.library = library
    app.state.media = media
    app.state.control = control
    app.state.comments = comments
    app.state.notifier = notifier

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
    add_ready_check(app, "comments", lambda: health_check(comments))

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
            await asyncio.sleep(10)

    sync_task = asyncio.create_task(registry_sync())
    warm_task = asyncio.create_task(warm_sitemap_cache(app))
    logger.info("gateway ready")
    try:
        yield
    finally:
        sync_task.cancel()
        warm_task.cancel()
        await asyncio.gather(sync_task, warm_task, return_exceptions=True)
        await asyncio.gather(
            catalog.close(), parser.close(), library.close(), media.close(), control.close(),
            comments.close(), notifier.close(),
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
    suggest_limit=settings.gateway_suggest_limit_per_minute,
    import_limit=settings.gateway_import_limit_per_minute,
)


@app.middleware("http")
async def client_identity(request, call_next):  # type: ignore[no-untyped-def]
    """Give every browser/device a stable id for per-client server affinity."""

    key = request.cookies.get("mp_client") or request.headers.get("X-Client-ID")
    if key is not None:
        key = key.strip()[:128]
    fresh = not key
    if not key:
        forwarded = request.headers.get("X-Forwarded-For", "")
        ip = forwarded.split(",")[0].strip() if forwarded else (
            request.client.host if request.client else ""
        )
        agent = request.headers.get("User-Agent", "")
        key = hashlib.sha256(f"{ip}\0{agent}".encode()).hexdigest()[:32]
    token = set_client_key(key)
    try:
        response = await call_next(request)
    finally:
        reset_client_key(token)
    if fresh:
        response.set_cookie(
            "mp_client",
            key,
            max_age=365 * 24 * 60 * 60,
            samesite="lax",
            httponly=False,
        )
    return response


app.include_router(router)
app.include_router(retention_router)
app.include_router(comments_router)
app.include_router(seo_router)
app.include_router(notifications_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.debug)
