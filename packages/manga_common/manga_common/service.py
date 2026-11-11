from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import Settings
from .errors import AppError, app_error_handler
from .logging import (
    Timing,
    configure_logging,
    log_event,
    new_request_id,
    request_id_ctx,
)
from .version import SERVICE_VERSION

ReadinessCheck = Callable[[], Awaitable[bool]]


def create_service_app(
    *,
    settings: Settings,
    title: str,
    description: str,
    version: str = SERVICE_VERSION,
    docs: bool = True,
) -> FastAPI:
    configure_logging(settings.log_level, settings.log_json, settings.service_name)

    app = FastAPI(
        title=title,
        description=description,
        version=version,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.settings = settings
    app.state.ready_checks = {}
    app.state.started = False

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "Content-Disposition", "ETag"],
    )

    @app.middleware("http")
    async def observability(request: Request, call_next):  # type: ignore[no-untyped-def]
        rid = request.headers.get("X-Request-ID") or new_request_id()
        token = request_id_ctx.set(rid)
        timing = Timing()
        try:
            response = await call_next(request)
        except Exception:
            log_event(
                __import__("logging").getLogger(settings.service_name),
                "request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=timing.elapsed_ms,
            )
            raise
        finally:
            request_id_ctx.reset(token)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        log_event(
            __import__("logging").getLogger(settings.service_name),
            "request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=timing.elapsed_ms,
        )
        return response

    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": settings.service_name,
            "version": version,
            "checks": {},
        }

    @app.get("/ready", tags=["system"])
    async def ready() -> JSONResponse:
        checks: dict[str, bool] = {}
        for name, check in app.state.ready_checks.items():
            try:
                checks[name] = await asyncio.wait_for(check(), timeout=3.0)
            except Exception:
                checks[name] = False
        ok = all(checks.values()) if checks else True
        return JSONResponse(
            {"status": "ready" if ok else "degraded", "checks": checks},
            status_code=200 if ok else 503,
        )

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "service": settings.service_name,
            "version": version,
            "docs": "/docs",
            "health": "/health",
            "ready": "/ready",
        }

    return app


def add_ready_check(app: FastAPI, name: str, check: ReadinessCheck) -> None:
    app.state.ready_checks[name] = check
