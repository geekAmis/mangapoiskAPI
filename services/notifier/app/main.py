from __future__ import annotations

import html
import logging

import httpx
from fastapi import APIRouter, Depends
from manga_common.config import Settings
from manga_common.errors import UpstreamError
from manga_common.http import build_client
from manga_common.security import require_internal_token
from manga_common.service import create_service_app
from pydantic import BaseModel, Field

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


class NotifierSettings(Settings):
    service_name: str = "notifier"
    port: int = 8006


settings = NotifierSettings()
app = create_service_app(
    settings=settings,
    title="MangaPoisk Reborn — Notifier",
    description="Telegram delivery for new chapter events.",
)
router = APIRouter(prefix="/internal", dependencies=[Depends(require_internal_token)])

_http: httpx.AsyncClient | None = None


def client() -> httpx.AsyncClient:
    global _http
    if _http is None:
        _http = build_client(settings)
    return _http


async def send(text: str, parse_mode: str | None = "HTML", disable_preview: bool = True) -> dict:
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
        response = await client().post(url, json=payload, timeout=20.0)
    except httpx.HTTPError as exc:
        raise UpstreamError("Telegram request failed", details=str(exc)) from exc
    if response.status_code >= 400:
        raise UpstreamError(
            "Telegram rejected the message",
            details={"status": response.status_code, "body": response.text[:300]},
        )
    return {"sent": True}


@router.post("/notify")
async def notify(payload: NotifyRequest) -> dict:
    return await send(payload.text, payload.parse_mode, payload.disable_preview)


@router.post("/notify/new-chapters")
async def notify_new_chapters(payload: NewChaptersRequest) -> dict:
    lines = ["<b>Новые главы на MangaPoisk Reborn</b>", ""]
    for event in payload.events[:25]:
        title = html.escape(event.manga_title)
        label = html.escape(event.chapter_label)
        if event.url:
            link = html.escape(event.url, quote=True)
            lines.append(f'• <a href="{link}">{title}</a> — {label} <i>({event.source})</i>')
        else:
            lines.append(f"• <b>{title}</b> — {label} <i>({event.source})</i>")
    return await send("\n".join(lines))


@router.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "service": settings.service_name,
        "telegram_configured": bool(settings.telegram_bot_token and settings.telegram_chat_id),
    }


app.include_router(router)


@app.on_event("shutdown")
async def shutdown() -> None:
    if _http is not None:
        await _http.aclose()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port)
