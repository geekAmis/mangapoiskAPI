from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from .auth import constant_time_compare
from .config import Settings
from .errors import AppError, UnauthorizedError, app_error_handler
from .logging import (
    Timing,
    configure_logging,
    log_event,
    new_request_id,
    request_id_ctx,
)
from .metrics import metrics
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
    metrics.set_service(settings.service_name)
    logger = logging.getLogger(settings.service_name)

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
    app.state.metrics = metrics
    app.state.metrics_collectors: list[Callable[[], Awaitable[None]]] = []

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
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            log_event(
                logger,
                "request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=timing.elapsed_ms,
            )
            raise
        finally:
            request_id_ctx.reset(token)
            # Do not count scrapes of /metrics itself: otherwise a 15-second
            # Prometheus interval dominates the latency window on idle nodes.
            if request.url.path != "/metrics":
                metrics.observe_http(
                    request.method, status_code, timing.elapsed_ms / 1000.0
                )
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        log_event(
            logger,
            "request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=timing.elapsed_ms,
        )
        return response

    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]

    @app.get("/metrics", include_in_schema=False)
    async def metrics_endpoint(
        request: Request,
        fmt: str = Query(default="prometheus", alias="format"),
    ):  # type: ignore[no-untyped-def]
        """Prometheus text by default, JSON with ``?format=json``.

        The payload contains counters and gauges only.  When ``METRICS_TOKEN``
        is configured it must be sent as ``X-Metrics-Token`` or a bearer token.
        """

        if settings.metrics_token:
            provided = request.headers.get("X-Metrics-Token", "")
            authorization = request.headers.get("Authorization", "")
            if authorization.lower().startswith("bearer "):
                provided = authorization[7:].strip()
            if not constant_time_compare(provided, settings.metrics_token):
                raise UnauthorizedError(
                    "Metrics token required", code="metrics_unauthorized"
                )
        for collector in list(app.state.metrics_collectors):
            try:
                await collector()
            except Exception:
                logger.exception("metrics collector failed")
                metrics.inc("mangapoisk_metrics_collector_errors_total")
        if fmt.lower() in {"json", "application/json"}:
            # The gateway installs a provider that returns the aggregated
            # observability snapshot (service health, crawler, backup, disk)
            # instead of only this process's counters.  Other services fall
            # back to the local registry.
            provider = getattr(app.state, "metrics_snapshot_provider", None)
            if provider is not None:
                try:
                    payload = provider()
                    if isinstance(payload, dict):
                        return JSONResponse(payload)
                except Exception:
                    logger.exception("metrics snapshot provider failed")
                    metrics.inc("mangapoisk_metrics_provider_errors_total")
            return JSONResponse(metrics.snapshot())
        return PlainTextResponse(
            metrics.render_prometheus(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

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
