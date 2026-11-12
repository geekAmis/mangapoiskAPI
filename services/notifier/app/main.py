from __future__ import annotations

import html
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Request
from manga_common.db import create_all, create_engine, create_session_factory, ping
from manga_common.errors import UpstreamError, ValidationError
from manga_common.http import build_client
from manga_common.security import require_internal_token
from manga_common.service import add_ready_check, create_service_app
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.engine import make_url

from .config import NotifierSettings
from .push import PushSender, PushService

logger = logging.getLogger(__name__)


class NotifyRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4096)
    parse_mode: str | None = "HTML"
    disable_preview: bool = True


class ChapterEvent(BaseModel):
    manga_title: str
    chapter_label: str
    source: str
    url: str | None = None


class NewChaptersRequest(BaseModel):
    events: list[ChapterEvent] = Field(min_length=1, max_length=50)


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=255)
    auth: str = Field(min_length=1, max_length=64)


class PushSubscribeRequest(BaseModel):
    user_id: uuid.UUID
    endpoint: str = Field(min_length=1, max_length=2048)
    keys: PushKeys
    user_agent: str | None = Field(default=None, max_length=512)


class PushUnsubscribeRequest(BaseModel):
    user_id: uuid.UUID
    endpoint: str = Field(min_length=1, max_length=2048)


class PushEventIn(BaseModel):
    manga_id: uuid.UUID
    chapter_id: uuid.UUID
    manga_title: str = Field(min_length=1, max_length=255)
    chapter_label: str = Field(min_length=1, max_length=128)
    chapter_url: str | None = Field(default=None, max_length=2048)
    source: str | None = Field(default=None, max_length=64)

    @field_validator("manga_title", "chapter_label")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class PushRecipientIn(BaseModel):
    user_id: uuid.UUID
    max_pushes_per_hour: int = Field(default=5, ge=1, le=60)
    quiet_hours_start: int | None = Field(default=None, ge=0, le=23)
    quiet_hours_end: int | None = Field(default=None, ge=0, le=23)


class PushChaptersRequest(BaseModel):
    events: list[PushEventIn] = Field(min_length=1, max_length=50)
    recipients: list[PushRecipientIn] = Field(default_factory=list, max_length=10000)


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


def create_app(
    settings: NotifierSettings | None = None,
    *,
    sender: PushSender | None = None,
    clock=None,  # type: ignore[no-untyped-def]
):
    settings = settings or NotifierSettings()

    @asynccontextmanager
    async def lifespan(app):  # type: ignore[no-untyped-def]
        if settings.is_production and (
            not settings.internal_token or settings.internal_token.startswith(("dev-", "change-me"))
        ):
            raise RuntimeError("INTERNAL_TOKEN must be changed in production")
        _ensure_sqlite_directory(settings.notifier_dsn)
        engine = create_engine(settings.notifier_dsn, echo=settings.debug)
        session_factory = create_session_factory(engine)
        await create_all(engine)
        app.state.engine = engine
        app.state.session_factory = session_factory
        app.state.push = PushService(
            settings, session_factory, sender=sender, clock=clock
        )
        app.state.http = build_client(settings)

        async def db_ready() -> bool:
            return await ping(engine)

        add_ready_check(app, "database", db_ready)
        logger.info(
            "notifier ready; web_push_configured=%s", app.state.push.configured
        )
        try:
            yield
        finally:
            await app.state.http.aclose()
            await engine.dispose()

    app = create_service_app(
        settings=settings,
        title="MangaPoisk Reborn — Notifier",
        description="Telegram and Web Push delivery for chapter events.",
    )
    app.router.lifespan_context = lifespan
    app.include_router(router)
    return app


router = APIRouter(prefix="/internal", dependencies=[Depends(require_internal_token)])


def push_service(request: Request) -> PushService:
    return request.app.state.push


async def send(
    request: Request,
    text: str,
    parse_mode: str | None = "HTML",
    disable_preview: bool = True,
) -> dict[str, Any]:
    settings: NotifierSettings = request.app.state.settings
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        logger.info("telegram is not configured; dropping notification")
        return {"sent": False, "reason": "telegram_not_configured"}
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": text[:4096],
        "disable_web_page_preview": disable_preview,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        response = await request.app.state.http.post(url, json=payload, timeout=20.0)
    except httpx.HTTPError as exc:
        raise UpstreamError("Telegram request failed", details=str(exc)) from exc
    if response.status_code >= 400:
        raise UpstreamError(
            "Telegram rejected the message",
            details={"status": response.status_code, "body": response.text[:300]},
        )
    return {"sent": True}


@router.post("/notify")
async def notify(request: Request, payload: NotifyRequest) -> dict[str, Any]:
    return await send(request, payload.text, payload.parse_mode, payload.disable_preview)


@router.post("/notify/new-chapters")
async def notify_new_chapters(
    request: Request, payload: NewChaptersRequest
) -> dict[str, Any]:
    lines = ["<b>Новые главы на MangaPoisk Reborn</b>", ""]
    for event in payload.events[:25]:
        title = html.escape(event.manga_title)
        label = html.escape(event.chapter_label)
        if event.url:
            link = html.escape(event.url, quote=True)
            lines.append(f'• <a href="{link}">{title}</a> — {label} <i>({event.source})</i>')
        else:
            lines.append(f"• <b>{title}</b> — {label} <i>({event.source})</i>")
    return await send(request, "\n".join(lines))


@router.get("/push/public-key")
async def push_public_key(request: Request) -> dict[str, Any]:
    return push_service(request).config()


@router.post("/push/subscribe")
async def push_subscribe(
    request: Request, payload: PushSubscribeRequest
) -> dict[str, Any]:
    try:
        return await push_service(request).subscribe(
            user_id=payload.user_id,
            endpoint=payload.endpoint,
            p256dh=payload.keys.p256dh,
            auth=payload.keys.auth,
            user_agent=payload.user_agent,
        )
    except ValueError as exc:
        raise ValidationError(str(exc), code="invalid_push_subscription") from exc


@router.delete("/push/subscribe")
async def push_unsubscribe(
    request: Request, payload: PushUnsubscribeRequest
) -> dict[str, Any]:
    removed = await push_service(request).unsubscribe(
        user_id=payload.user_id, endpoint=payload.endpoint
    )
    return {"unsubscribed": removed}


@router.get("/push/status")
async def push_status(request: Request, user_id: uuid.UUID) -> dict[str, Any]:
    return await push_service(request).status(user_id)


@router.post("/push/chapters")
async def push_chapters(
    request: Request, payload: PushChaptersRequest
) -> dict[str, Any]:
    events = [event.model_dump(mode="json") for event in payload.events]
    recipients = [recipient.model_dump(mode="json") for recipient in payload.recipients]
    return await push_service(request).send_chapters(events=events, recipients=recipients)


@router.get("/health")
async def internal_health(request: Request) -> dict[str, Any]:
    settings: NotifierSettings = request.app.state.settings
    push = push_service(request)
    return {
        "status": "ok",
        "service": settings.service_name,
        "telegram_configured": bool(
            settings.telegram_bot_token and settings.telegram_chat_id
        ),
        "web_push_configured": push.configured,
    }


settings = NotifierSettings()
app = create_app(settings)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port)
