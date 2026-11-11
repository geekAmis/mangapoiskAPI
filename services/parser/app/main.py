"""Parser service entry point (port 8001)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from manga_common.cache import create_cache
from manga_common.config import Settings, get_settings
from manga_common.errors import error_body
from manga_common.http import build_client
from manga_common.logging import log_event
from manga_common.service import add_ready_check, create_service_app
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import router
from .registry import build_registry
from .settings import ParserSettings

logger = logging.getLogger("parser")


async def _validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    details = [
        {
            "loc": list(error.get("loc", ())),
            "msg": error.get("msg", "Invalid value"),
            "type": error.get("type", "value_error"),
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        error_body("validation_error", "Invalid request parameters", details),
        status_code=422,
    )


async def _http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = "not_found" if exc.status_code == 404 else "http_error"
    message = str(exc.detail) if exc.detail else "Request failed"
    return JSONResponse(
        error_body(code, message),
        status_code=exc.status_code,
        headers=getattr(exc, "headers", None),
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the parser app.  Tests may inject their own settings."""

    runtime_settings = settings or ParserSettings()
    app = create_service_app(
        settings=runtime_settings,
        title="MangaPoisk Reborn — Parser",
        description=(
            "Internal source adapter service. Fetches public catalogue metadata "
            "politely, normalises it and never proxies user credentials."
        ),
        docs=not runtime_settings.is_production,
    )
    # Shared services resolve settings through get_settings(); pin the same
    # instance so tokens and scraper limits are consistent in tests and runtime.
    app.dependency_overrides[get_settings] = lambda: runtime_settings
    app.add_exception_handler(RequestValidationError, _validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)  # type: ignore[arg-type]

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        current: Settings = application.state.settings or ParserSettings()
        client = build_client(current)
        cache = create_cache(current.redis_url)
        registry = build_registry(client, current, cache)
        application.state.http_client = client
        application.state.cache = cache
        application.state.registry = registry
        add_ready_check(application, "cache", cache.ping)
        log_event(
            logger,
            "parser_started",
            sources=registry.codes(),
            enabled=[adapter.info.code for adapter in registry.adapters if adapter.info.enabled],
            cache=type(cache).__name__,
        )
        try:
            yield
        finally:
            try:
                await client.aclose()
            except Exception as exc:
                log_event(logger, "http_client_close_failed", error=type(exc).__name__)
            try:
                await cache.close()
            except Exception as exc:
                log_event(logger, "cache_close_failed", error=type(exc).__name__)
            log_event(logger, "parser_stopped")

    app.router.lifespan_context = lifespan
    app.include_router(router)
    return app


settings = ParserSettings()
app = create_app(settings)


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=8001,
        reload=settings.debug,
    )
