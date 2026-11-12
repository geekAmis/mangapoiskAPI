from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from manga_common.auth import constant_time_compare, create_access_token
from manga_common.errors import (
    NotFoundError,
    RateLimitError,
    UnauthorizedError,
    UpstreamError,
    ValidationError,
)
from manga_common.schemas import (
    BookmarkCreate,
    BookmarkOut,
    ChapterDetailOut,
    ChapterOut,
    ExportJobOut,
    ImportMangaRequest,
    ImportMangaResponse,
    LoginRequest,
    LogoutRequest,
    MangaDetailOut,
    MangaListResponse,
    MangaOut,
    MangaVariantsOut,
    OkResponse,
    PageOut,
    Paginated,
    ProgressOut,
    ProgressUpsert,
    ReaderSettings,
    RefreshRequest,
    RegisterRequest,
    SearchResponse,
    SourceOut,
    TokenPair,
    UserOut,
)
from manga_common.security import (
    UserClaims,
    admin_auth_version,
    require_admin,
    require_internal_token,
    require_user,
)
from manga_common.source_models import MangaSummary, SourceSearchResult
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from .clients import CatalogClient, ControlClient, LibraryClient, MediaClient, ParserClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")

# Five failed admin logins per IP per five minutes.  The generic middleware
# limit is intentionally generous for readers; admin auth needs its own gate.
_ADMIN_WINDOW_SECONDS = 300.0
_ADMIN_MAX_FAILURES = 5
_admin_failures: dict[str, list[float]] = {}


def _admin_failure_times(ip: str) -> list[float]:
    now = time.monotonic()
    recent = [stamp for stamp in _admin_failures.get(ip, []) if now - stamp < _ADMIN_WINDOW_SECONDS]
    if recent:
        _admin_failures[ip] = recent
    return recent


def _check_admin_login_rate(ip: str) -> None:
    if len(_admin_failure_times(ip)) >= _ADMIN_MAX_FAILURES:
        raise RateLimitError(
            "Слишком много попыток входа. Попробуйте через несколько минут.",
            code="admin_rate_limited",
        )


def _record_admin_failure(ip: str) -> None:
    recent = _admin_failure_times(ip)
    recent.append(time.monotonic())
    _admin_failures[ip] = recent[-20:]


def clients(request: Request) -> tuple[CatalogClient, ParserClient, LibraryClient, MediaClient]:
    state = request.app.state
    return state.catalog, state.parser, state.library, state.media


def _authorization(request: Request) -> str:
    return request.headers.get("Authorization", "")


def _client_ip(request: Request) -> str:
    # nginx overwrites X-Real-IP with the peer address.  Never trust the first
    # X-Forwarded-For element: it is client-controlled and would let a caller
    # reset rate-limit buckets at will.
    real_ip = request.headers.get("X-Real-IP", "").strip()
    if real_ip:
        return real_ip
    return request.client.host if request.client else "unknown"


def _public_chapter(detail: ChapterDetailOut) -> ChapterDetailOut:
    pages = [
        PageOut(
            number=page.number,
            url=f"/api/v1/chapters/{detail.id}/images/{page.number}",
            width=page.width,
            height=page.height,
        )
        for page in detail.pages
    ]
    return detail.model_copy(update={"pages": pages})


def _chapter_label(chapter: ChapterOut) -> str:
    parts = []
    if chapter.volume:
        parts.append(f"Том {chapter.volume}")
    parts.append(f"Глава {chapter.number}")
    if chapter.title:
        parts.append(chapter.title)
    return ", ".join(parts)


# Chapter ids already posted to the media archive in this process.  The media
# endpoint is idempotent, this simply avoids one request per reader page view.
_archive_posted: set[str] = set()
_archive_tasks: set[asyncio.Task] = set()
_warm_tasks: set[asyncio.Task] = set()


async def _post_archive(media: MediaClient, payload: dict[str, Any], key: str) -> None:
    try:
        result = await media.archive_chapter(payload)
        if isinstance(result, dict) and result.get("status") == "failed":
            _archive_posted.discard(key)
    except Exception as exc:
        _archive_posted.discard(key)
        logger.debug("chapter archive request failed for %s: %s", key, exc)


def _schedule_archive(request: Request, detail: ChapterDetailOut) -> None:
    if not detail.pages:
        return
    key = str(detail.id)
    if key in _archive_posted:
        return
    if len(_archive_posted) >= 5000:
        _archive_posted.clear()
    _archive_posted.add(key)
    payload = {
        "chapter_id": key,
        "source": detail.source,
        "translator": getattr(detail, "translator", None),
        "pages": [
            {
                "number": page.number,
                "url": page.url,
                "width": page.width,
                "height": page.height,
            }
            for page in detail.pages
        ],
    }
    task = asyncio.create_task(_post_archive(request.app.state.media, payload, key))
    _archive_tasks.add(task)
    task.add_done_callback(_archive_tasks.discard)


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------


@router.get("/registry", dependencies=[Depends(require_internal_token)])
async def internal_registry(request: Request) -> dict[str, Any]:
    """Registry feed for replica nodes; internal token only."""

    return await control(request).registry()


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    catalog, parser, library, media = clients(request)
    services = {
        "catalog": catalog,
        "parser": parser,
        "library": library,
        "media": media,
    }

    async def check(name: str, client: Any) -> tuple[str, bool]:
        try:
            response = await client.client.get("/health", timeout=3.0)
            return name, response.status_code == 200
        except Exception:
            return name, False

    results = await asyncio.gather(*(check(name, client) for name, client in services.items()))
    checks = dict(results)
    return {
        "status": "ok" if all(checks.values()) else "degraded",
        "service": "gateway",
        "version": "1.0.0",
        "checks": checks,
    }


@router.get("/sources", response_model=list[SourceOut])
async def sources(request: Request) -> list[SourceOut]:
    catalog, parser, _, _ = clients(request)
    items: list[SourceOut] = []
    try:
        items = await catalog.sources()
    except Exception:
        items = []
    if items:
        return items
    try:
        info = await parser.sources()
    except Exception:
        return []
    return [
        SourceOut(
            code=source.code,
            name=source.name,
            base_url=source.base_url,
            language=source.language,
            enabled=source.enabled,
            requires_cookies=source.requires_cookies,
            capabilities=source.capabilities.model_dump(),
        )
        for source in info
    ]


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------


@router.get("/manga", response_model=MangaListResponse)
async def manga_list(
    request: Request,
    query: str | None = Query(default=None, max_length=200),
    source: str | None = Query(default=None, max_length=64),
    genre: str | None = Query(default=None, max_length=64),
    year: int | None = Query(default=None, ge=1900, le=2100),
    status: str | None = Query(default=None, max_length=64),
    sort: str = Query(default="popular", pattern="^(popular|rating|updated|title|new)$"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=24, ge=1, le=100),
) -> MangaListResponse:
    catalog, _, _, _ = clients(request)
    params: dict[str, Any] = {"sort": sort, "page": page, "limit": limit}
    if query:
        params["query"] = query
    if source:
        params["source"] = source
    if genre:
        params["genre"] = genre
    if year:
        params["year"] = year
    if status:
        params["status"] = status
    return await catalog.manga_list(params)


async def _live_search(
    request: Request, q: str, source: str | None, page: int, limit: int
) -> tuple[list[MangaOut], int]:
    catalog, parser, _, _ = clients(request)
    source_codes: list[str] = []
    if source:
        source_codes = [source]
    else:
        try:
            info = await parser.sources()
            source_codes = [
                item.code
                for item in info
                if item.enabled and item.capabilities.search
            ][: request.app.state.settings.live_search_max_sources]
        except Exception:
            source_codes = []
    if not source_codes:
        return [], 0

    results = await asyncio.gather(
        *(parser.search(code, q, page) for code in source_codes), return_exceptions=True
    )
    summaries: list[MangaSummary] = []
    seen: set[tuple[str, str]] = set()
    for raw in results:
        if isinstance(raw, Exception) or not isinstance(raw, dict):
            continue
        try:
            parsed = SourceSearchResult.model_validate(raw)
        except Exception:
            continue
        for item in parsed.items:
            key = (item.source, item.source_id)
            if key in seen:
                continue
            seen.add(key)
            summaries.append(item)
    summaries.sort(key=lambda item: (item.rating or 0, item.rating_count or 0), reverse=True)
    summaries = summaries[: request.app.state.settings.live_search_import_limit]

    semaphore = asyncio.Semaphore(5)

    async def import_one(summary: MangaSummary) -> MangaOut | None:
        async with semaphore:
            try:
                return await catalog.import_summary(summary)
            except Exception as exc:
                logger.debug("live search import failed for %s: %s", summary.title, exc)
                return None

    imported = await asyncio.gather(*(import_one(item) for item in summaries))
    items = [item for item in imported if item is not None]
    return items, len(items)


@router.get("/manga/search", response_model=SearchResponse)
async def manga_search(
    request: Request,
    q: str = Query(min_length=1, max_length=200),
    source: str | None = Query(default=None, max_length=64),
    live: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=24, ge=1, le=100),
) -> SearchResponse:
    catalog, _, _, _ = clients(request)
    local = await catalog.search(q, source=source, page=page, limit=limit)
    if local.items and not live:
        return SearchResponse(
            items=local.items,
            total=local.total,
            page=local.page,
            limit=local.limit,
            has_next=local.has_next,
            live=False,
        )
    try:
        live_items, live_total = await _live_search(request, q, source, page, limit)
    except Exception as exc:
        logger.warning("live search failed: %s", exc)
        live_items, live_total = [], 0
    if live_items:
        return SearchResponse(
            items=live_items,
            total=max(live_total, local.total),
            page=page,
            limit=limit,
            has_next=len(live_items) >= limit,
            live=True,
        )
    return SearchResponse(
        items=local.items,
        total=local.total,
        page=local.page,
        limit=local.limit,
        has_next=local.has_next,
        live=False,
    )


@router.post("/manga/import", response_model=ImportMangaResponse)
async def import_manga(request: Request, payload: ImportMangaRequest) -> ImportMangaResponse:
    catalog, _, _, _ = clients(request)
    if not payload.url and not payload.source_id:
        raise ValidationError("Укажите url или source_id")
    result = await catalog.import_manga(payload.source, source_id=payload.source_id, url=payload.url)
    manga = MangaDetailOut.model_validate(result["manga"])
    return ImportMangaResponse(
        manga=manga,
        source=result.get("source", payload.source),
        imported_chapters=result.get("imported_chapters", 0),
        imported_pages=result.get("imported_pages", 0),
    )


@router.get("/manga/{manga_id}/variants", response_model=MangaVariantsOut)
async def manga_variants(request: Request, manga_id: uuid.UUID) -> MangaVariantsOut:
    catalog, _, _, _ = clients(request)
    return await catalog.variants(str(manga_id))


@router.post("/manga/{manga_id}/warm")
async def warm_manga(
    request: Request,
    manga_id: uuid.UUID,
    user: UserClaims = Depends(require_user),
) -> dict[str, Any]:
    """Queue server-side archiving for every chapter of a title.

    A user downloading a whole work triggers this; later readers get the pages
    from our archive instead of the upstream source.  Chapters that appear
    later still need their first read to be archived.
    """

    catalog, _, _, media = clients(request)
    detail = await catalog.manga(str(manga_id))

    async def worker() -> None:
        semaphore = asyncio.Semaphore(2)

        async def one(chapter: ChapterOut) -> None:
            async with semaphore:
                try:
                    chapter_detail = await catalog.chapter(str(chapter.id))
                    if not chapter_detail.pages:
                        return
                    await media.archive_chapter(
                        {
                            "chapter_id": str(chapter_detail.id),
                            "source": chapter_detail.source,
                            "translator": getattr(chapter_detail, "translator", None),
                            "pages": [
                                {"number": page.number, "url": page.url}
                                for page in chapter_detail.pages
                            ],
                        }
                    )
                except Exception as exc:
                    logger.debug("warm chapter failed %s: %s", chapter.id, exc)

        await asyncio.gather(*(one(chapter) for chapter in detail.chapters))

    task = asyncio.create_task(worker())
    _warm_tasks.add(task)
    task.add_done_callback(_warm_tasks.discard)
    return {"queued": len(detail.chapters), "manga_id": str(manga_id)}


@router.get("/manga/{manga_id}", response_model=MangaDetailOut)
async def manga_detail(request: Request, manga_id: uuid.UUID) -> MangaDetailOut:
    catalog, _, _, _ = clients(request)
    detail = await catalog.manga(str(manga_id))
    if not detail.chapters and detail.source_id:
        try:
            result = await catalog.import_manga(
                detail.source, source_id=detail.source_id, url=detail.url
            )
            return MangaDetailOut.model_validate(result["manga"])
        except Exception as exc:
            logger.info("lazy manga hydration failed for %s: %s", manga_id, exc)
    return detail


@router.get("/manga/{manga_id}/chapters", response_model=Paginated[ChapterOut])
async def manga_chapters(
    request: Request,
    manga_id: uuid.UUID,
    query: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=200, ge=1, le=500),
) -> Paginated[ChapterOut]:
    catalog, _, _, _ = clients(request)
    items = await catalog.chapters(
        str(manga_id), page=page, limit=limit, query=query
    )
    return Paginated(
        items=items,
        total=(page - 1) * limit + len(items) + (1 if len(items) >= limit else 0),
        page=page,
        limit=limit,
        has_next=len(items) >= limit,
    )


# ---------------------------------------------------------------------------
# Reader
# ---------------------------------------------------------------------------


@router.get("/chapters/{chapter_id}", response_model=ChapterDetailOut)
async def chapter_detail(
    request: Request,
    chapter_id: uuid.UUID,
    refresh: bool = Query(default=True),
) -> ChapterDetailOut:
    catalog, _, _, _ = clients(request)
    detail = await catalog.chapter(str(chapter_id), refresh=refresh)
    _schedule_archive(request, detail)
    return _public_chapter(detail)


@router.get("/chapters/{chapter_id}/pages", response_model=list[PageOut])
async def chapter_pages(request: Request, chapter_id: uuid.UUID) -> list[PageOut]:
    catalog, _, _, _ = clients(request)
    detail = await catalog.chapter(str(chapter_id))
    return _public_chapter(detail).pages


@router.get("/chapters/{chapter_id}/images/{number}")
async def chapter_image(
    request: Request, chapter_id: uuid.UUID, number: int
) -> StreamingResponse:
    catalog, _, _, media = clients(request)
    # Prefer the server-side archive: a chapter fetched by any user once is
    # served from media without touching the original source again.
    response = await media.archived_page(str(chapter_id), number)
    if response.status_code != 200:
        if response.status_code != 404:
            logger.debug(
                "archive page lookup failed for %s/%s: %s",
                chapter_id,
                number,
                response.status_code,
            )
        await response.aread()
        await response.aclose()
        detail = await catalog.chapter(str(chapter_id))
        page = next((item for item in detail.pages if item.number == number), None)
        if page is None:
            raise NotFoundError("Страница не найдена")
        response = await media.image(page.url)
    if response.status_code >= 400:
        body = await response.aread()
        await response.aclose()
        raise UpstreamError(
            "Не удалось получить изображение",
            details={"status": response.status_code, "body": body[:200].decode(errors="ignore")},
        )
    headers = {
        key: value
        for key, value in response.headers.items()
        if key.lower() in {"content-type", "content-length", "etag", "cache-control"}
    }
    return StreamingResponse(
        response.aiter_raw(),
        status_code=response.status_code,
        headers=headers,
        background=BackgroundTask(response.aclose),
    )


@router.post("/chapters/{chapter_id}/exports", response_model=ExportJobOut)
async def create_export(
    request: Request,
    chapter_id: uuid.UUID,
    format: Literal["cbz", "pdf", "html"] = Query(default="cbz"),
) -> ExportJobOut:
    catalog, _, _, media = clients(request)
    detail = await catalog.chapter(str(chapter_id))
    if not detail.pages:
        raise ValidationError("В этой главе нет страниц для экспорта")
    manga = await catalog.manga(str(detail.manga_id))
    payload = {
        "chapter_id": str(chapter_id),
        "manga_title": manga.title,
        "chapter_label": _chapter_label(detail),
        "format": format,
        "pages": [{"number": page.number, "url": page.url} for page in detail.pages],
        "referer": manga.url,
    }
    job = await media.create_export(payload)
    return job.model_copy(update={"download_url": f"/api/v1/exports/{job.id}/download"})


@router.get("/exports/{job_id}", response_model=ExportJobOut)
async def export_status(request: Request, job_id: uuid.UUID) -> ExportJobOut:
    _, _, _, media = clients(request)
    job = await media.export(str(job_id))
    return job.model_copy(
        update={
            "download_url": f"/api/v1/exports/{job.id}/download"
            if job.status == "done"
            else None
        }
    )


@router.get("/exports/{job_id}/download")
async def export_download(request: Request, job_id: uuid.UUID) -> StreamingResponse:
    _, _, _, media = clients(request)
    response = await media.download(str(job_id))
    if response.status_code >= 400:
        body = await response.aread()
        await response.aclose()
        raise NotFoundError("Экспорт не готов", details=body[:200].decode(errors="ignore"))
    headers = {
        key: value
        for key, value in response.headers.items()
        if key.lower() in {"content-type", "content-length", "content-disposition"}
    }
    return StreamingResponse(
        response.aiter_raw(),
        status_code=response.status_code,
        headers=headers,
        background=BackgroundTask(response.aclose),
    )


@router.delete("/exports/{job_id}", response_model=OkResponse)
async def delete_export(request: Request, job_id: uuid.UUID) -> OkResponse:
    _, _, _, media = clients(request)
    await media.delete_export(str(job_id))
    return OkResponse(message="Экспорт удалён")


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def _forward_meta(request: Request) -> dict[str, str]:
    return {
        "User-Agent": request.headers.get("User-Agent", "")[:512],
        "X-Client-IP": _client_ip(request),
    }


@router.post("/auth/register", response_model=TokenPair)
async def register(request: Request, payload: RegisterRequest) -> TokenPair:
    _, _, library, _ = clients(request)
    return await library.register(
        payload.model_dump(mode="json"), headers=_forward_meta(request)
    )


@router.post("/auth/login", response_model=TokenPair)
async def login(request: Request, payload: LoginRequest) -> TokenPair:
    _, _, library, _ = clients(request)
    return await library.login(payload.model_dump(mode="json"), headers=_forward_meta(request))


@router.post("/auth/refresh", response_model=TokenPair)
async def refresh(request: Request, payload: RefreshRequest) -> TokenPair:
    _, _, library, _ = clients(request)
    return await library.refresh(payload.refresh_token)


@router.post("/auth/logout", response_model=OkResponse)
async def logout(request: Request, payload: LogoutRequest) -> OkResponse:
    _, _, library, _ = clients(request)
    await library.logout(payload.refresh_token)
    return OkResponse(message="Вы вышли из аккаунта")


@router.get("/auth/me", response_model=UserOut)
async def me(request: Request, user: UserClaims = Depends(require_user)) -> UserOut:
    _, _, library, _ = clients(request)
    return await library.me(_authorization(request))


# ---------------------------------------------------------------------------
# Library
# ---------------------------------------------------------------------------


async def _enrich_bookmarks(
    catalog: CatalogClient, items: list[BookmarkOut]
) -> list[BookmarkOut]:
    semaphore = asyncio.Semaphore(6)

    async def enrich(item: BookmarkOut) -> BookmarkOut:
        if item.manga is not None:
            return item
        async with semaphore:
            try:
                manga = await catalog.manga(str(item.manga_id))
                return item.model_copy(update={"manga": manga})
            except Exception:
                return item

    return list(await asyncio.gather(*(enrich(item) for item in items)))


async def _enrich_progress(
    catalog: CatalogClient, items: list[ProgressOut]
) -> list[ProgressOut]:
    semaphore = asyncio.Semaphore(6)

    async def enrich(item: ProgressOut) -> ProgressOut:
        updates: dict[str, Any] = {}
        async with semaphore:
            with contextlib.suppress(Exception):
                updates["manga"] = await catalog.manga(str(item.manga_id))
            with contextlib.suppress(Exception):
                updates["chapter"] = await catalog.chapter_meta(str(item.chapter_id))
        return item.model_copy(update=updates) if updates else item

    return list(await asyncio.gather(*(enrich(item) for item in items)))


@router.get("/library/bookmarks", response_model=list[BookmarkOut])
async def list_bookmarks(
    request: Request, user: UserClaims = Depends(require_user)
) -> list[BookmarkOut]:
    catalog, _, library, _ = clients(request)
    items = await library.bookmarks(_authorization(request))
    return await _enrich_bookmarks(catalog, items)


@router.post("/library/bookmarks", response_model=BookmarkOut)
async def add_bookmark(
    request: Request,
    payload: BookmarkCreate,
    user: UserClaims = Depends(require_user),
) -> BookmarkOut:
    catalog, _, library, _ = clients(request)
    manga = await catalog.manga(str(payload.manga_id))
    bookmark = await library.add_bookmark(_authorization(request), str(payload.manga_id))
    return bookmark.model_copy(update={"manga": manga})


@router.delete("/library/bookmarks/{manga_id}", response_model=OkResponse)
async def remove_bookmark(
    request: Request,
    manga_id: uuid.UUID,
    user: UserClaims = Depends(require_user),
) -> OkResponse:
    _, _, library, _ = clients(request)
    await library.remove_bookmark(_authorization(request), str(manga_id))
    return OkResponse(message="Закладка удалена")


@router.get("/library/progress", response_model=list[ProgressOut])
async def library_progress(
    request: Request, user: UserClaims = Depends(require_user)
) -> list[ProgressOut]:
    catalog, _, library, _ = clients(request)
    items = await library.progress(_authorization(request))
    return await _enrich_progress(catalog, items)


@router.get("/library/history", response_model=list[ProgressOut])
async def library_history(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    user: UserClaims = Depends(require_user),
) -> list[ProgressOut]:
    catalog, _, library, _ = clients(request)
    items = await library.history(_authorization(request), limit=limit)
    return await _enrich_progress(catalog, items)


@router.put("/library/progress", response_model=ProgressOut)
async def upsert_progress(
    request: Request,
    payload: ProgressUpsert,
    user: UserClaims = Depends(require_user),
) -> ProgressOut:
    catalog, _, library, _ = clients(request)
    await catalog.manga(str(payload.manga_id))
    await catalog.chapter_meta(str(payload.chapter_id))
    item = await library.upsert_progress(_authorization(request), payload.model_dump(mode="json"))
    enriched = await _enrich_progress(catalog, [item])
    return enriched[0]


@router.delete("/library/progress/{manga_id}", response_model=OkResponse)
async def delete_progress(
    request: Request,
    manga_id: uuid.UUID,
    user: UserClaims = Depends(require_user),
) -> OkResponse:
    _, _, library, _ = clients(request)
    await library.delete_progress(_authorization(request), str(manga_id))
    return OkResponse(message="Прогресс сброшен")


@router.get("/library/settings", response_model=ReaderSettings)
async def get_reader_settings(
    request: Request, user: UserClaims = Depends(require_user)
) -> ReaderSettings:
    _, _, library, _ = clients(request)
    return await library.settings(_authorization(request))


@router.put("/library/settings", response_model=ReaderSettings)
async def save_reader_settings(
    request: Request,
    payload: ReaderSettings,
    user: UserClaims = Depends(require_user),
) -> ReaderSettings:
    _, _, library, _ = clients(request)
    return await library.save_settings(_authorization(request), payload)


# ---------------------------------------------------------------------------
# Admin / server manager
# ---------------------------------------------------------------------------


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=512)


class AdminToken(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    username: str


class AdminMe(BaseModel):
    username: str
    role: str = "admin"


def control(request: Request) -> ControlClient:
    return request.app.state.control


async def _apply_registry(target: Any, registry: dict[str, Any]) -> dict[str, str]:
    state = target.app.state if hasattr(target, "app") else target.state
    pool = getattr(state, "pool", None)
    if pool is not None:
        pool.update(registry)
    mapping: dict[str, Any] = {
        "parser": state.parser,
        "catalog": state.catalog,
        "library": state.library,
        "media": state.media,
    }
    updated: dict[str, str] = {}
    for code, client in mapping.items():
        items = registry.get("services", {}).get(code, [])
        candidates = sorted(
            items,
            key=lambda item: (bool(item.get("is_fallback")), not bool(item.get("healthy"))),
        )
        healthy = [item for item in candidates if item.get("healthy")]
        if not healthy:
            continue
        chosen = healthy[0]
        if chosen and chosen.get("url"):
            client.set_base_url(str(chosen["url"]))
            updated[code] = str(chosen["url"])
    return updated


@router.post("/admin/login", response_model=AdminToken)
async def admin_login(request: Request, payload: AdminLoginRequest) -> AdminToken:
    settings = request.app.state.settings
    client_ip = _client_ip(request)
    _check_admin_login_rate(client_ip)
    if not (
        constant_time_compare(payload.username, settings.admin_username)
        and constant_time_compare(payload.password, settings.admin_password)
    ):
        _record_admin_failure(client_ip)
        raise UnauthorizedError("Неверный логин или пароль администратора", code="admin_invalid")
    _admin_failures.pop(client_ip, None)
    token, expires_in = create_access_token(
        settings,
        subject="admin",
        role="admin",
        extra={"username": payload.username, "av": admin_auth_version(settings)},
        expires_minutes=settings.admin_token_minutes,
    )
    return AdminToken(
        access_token=token, expires_in=expires_in, username=payload.username
    )


@router.get("/admin/me", response_model=AdminMe)
async def admin_me(user: UserClaims = Depends(require_admin)) -> AdminMe:
    return AdminMe(username=str(user.raw.get("username", "admin")), role=user.role)


@router.get("/admin/servers")
async def admin_servers(
    request: Request, user: UserClaims = Depends(require_admin)
) -> list[dict[str, Any]]:
    return await control(request).servers()


@router.post("/admin/servers")
async def admin_create_server(
    request: Request,
    payload: dict[str, Any],
    user: UserClaims = Depends(require_admin),
) -> dict[str, Any]:
    return await control(request).create_server(payload)


@router.patch("/admin/servers/{server_id}")
async def admin_update_server(
    request: Request,
    server_id: uuid.UUID,
    payload: dict[str, Any],
    user: UserClaims = Depends(require_admin),
) -> dict[str, Any]:
    return await control(request).update_server(str(server_id), payload)


@router.delete("/admin/servers/{server_id}")
async def admin_delete_server(
    request: Request,
    server_id: uuid.UUID,
    user: UserClaims = Depends(require_admin),
) -> dict[str, Any]:
    await control(request).delete_server(str(server_id))
    return {"ok": True}


@router.post("/admin/servers/{server_id}/deploy")
async def admin_deploy_server(
    request: Request,
    server_id: uuid.UUID,
    payload: dict[str, Any],
    user: UserClaims = Depends(require_admin),
) -> dict[str, Any]:
    return await control(request).deploy(str(server_id), payload)


@router.get("/admin/servers/{server_id}/health")
async def admin_server_health(
    request: Request,
    server_id: uuid.UUID,
    user: UserClaims = Depends(require_admin),
) -> dict[str, Any]:
    return await control(request).server_health(str(server_id))


@router.post("/admin/servers/{server_id}/replica/promote")
async def admin_promote_replica(
    request: Request,
    server_id: uuid.UUID,
    user: UserClaims = Depends(require_admin),
) -> dict[str, Any]:
    return await control(request).promote_replica(str(server_id))


@router.post("/admin/servers/{server_id}/replica/bootstrap")
async def admin_bootstrap_replica(
    request: Request,
    server_id: uuid.UUID,
    payload: dict[str, Any],
    user: UserClaims = Depends(require_admin),
) -> dict[str, Any]:
    source = payload.get("source_server_id")
    try:
        source_id = uuid.UUID(str(source))
    except (TypeError, ValueError) as exc:
        raise ValidationError("Некорректный исходный сервер") from exc
    return await control(request).bootstrap_replica(str(server_id), str(source_id))


@router.get("/admin/jobs/{job_id}")
async def admin_job(
    request: Request,
    job_id: uuid.UUID,
    user: UserClaims = Depends(require_admin),
) -> dict[str, Any]:
    return await control(request).job(str(job_id))


@router.get("/admin/registry")
async def admin_registry(
    request: Request, user: UserClaims = Depends(require_admin)
) -> dict[str, Any]:
    return await control(request).registry()


@router.post("/admin/registry/sync")
async def admin_registry_sync(
    request: Request, user: UserClaims = Depends(require_admin)
) -> dict[str, Any]:
    registry = await control(request).refresh_registry()
    updated = await _apply_registry(request, registry)
    return {"updated": updated, "registry": registry}


@router.post("/admin/failover")
async def admin_failover(
    request: Request, user: UserClaims = Depends(require_admin)
) -> dict[str, Any]:
    registry = await control(request).refresh_registry()
    updated = await _apply_registry(request, registry)
    return {"updated": updated, "registry": registry}


@router.get("/admin/audit")
async def admin_audit(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    user: UserClaims = Depends(require_admin),
) -> list[dict[str, Any]]:
    return await control(request).audit(limit)
