from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile
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
    HomeUpdatesOut,
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


class PrepareChapterOut(BaseModel):
    id: str
    status: Literal["done", "pending", "error"]
    page_count: int = 0
    error: str | None = None


class PrepareStatusOut(BaseModel):
    manga_id: str
    total: int
    prepared: int
    pending: int
    failed: int
    batch: list[str]
    chapters: list[PrepareChapterOut]
    job_id: str | None = None
    error: str | None = None


class PrepareStartOut(BaseModel):
    job_id: str
    total: int
    chapter_ids: list[str]


@dataclass(slots=True)
class _PrepareJob:
    job_id: str
    manga_id: str
    chapter_ids: list[str]
    created_at: float
    errors: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    task: asyncio.Task[None] | None = None
    finished: bool = False


class _PrepareRegistry:
    """In-process dedupe for whole-title preparation.

    Chapter archiving itself is idempotent in the media service; this registry
    only prevents the gateway from spawning several identical background
    workers for one manga.  Persisted progress lives in ``chapter_archives``.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, _PrepareJob] = {}

    def active(self, manga_id: str) -> _PrepareJob | None:
        job = self._jobs.get(manga_id)
        if job is None:
            return None
        if job.finished or (job.task is not None and job.task.done()):
            self._jobs.pop(manga_id, None)
            return None
        return job

    def start(
        self,
        manga_id: str,
        chapter_ids: list[str],
        runner: Callable[[_PrepareJob], Awaitable[None]],
    ) -> tuple[_PrepareJob, bool]:
        existing = self.active(manga_id)
        if existing is not None:
            return existing, False
        job = _PrepareJob(
            job_id=str(uuid.uuid4()),
            manga_id=manga_id,
            chapter_ids=list(chapter_ids),
            created_at=time.monotonic(),
        )
        task = asyncio.create_task(runner(job))
        job.task = task
        self._jobs[manga_id] = job
        task.add_done_callback(lambda _completed, job=job: self._forget(job))
        return job, True

    def _forget(self, job: _PrepareJob) -> None:
        job.finished = True
        if self._jobs.get(job.manga_id) is job:
            self._jobs.pop(job.manga_id, None)


_prepare_registry = _PrepareRegistry()


def _build_prepare_status(
    manga_id: str,
    chapters: list[ChapterOut],
    summary: dict[str, dict[str, Any]],
    *,
    active: bool,
    job_errors: dict[str, str] | None = None,
    job_error: str | None = None,
    job_id: str | None = None,
) -> PrepareStatusOut:
    errors = job_errors or {}
    items: list[PrepareChapterOut] = []
    batch: list[str] = []
    prepared = 0
    failed = 0
    pending = 0
    for chapter in chapters:
        key = str(chapter.id)
        raw = summary.get(key) or {}
        raw_status = str(raw.get("status") or "missing")
        page_count = int(raw.get("page_count") or 0)
        message: str | None = None
        if raw_status == "done":
            status: Literal["done", "pending", "error"] = "done"
            prepared += 1
            if len(batch) < 5:
                batch.append(key)
        elif raw_status in {"queued", "running", "pending"}:
            status = "pending"
            pending += 1
        elif raw_status in {"failed", "error"}:
            status = "error"
            failed += 1
            message = str(raw.get("error") or errors.get(key) or "Не удалось подготовить главу")
        elif active:
            # The prepare worker has not reached this chapter yet.
            status = "pending"
            pending += 1
        else:
            status = "error"
            failed += 1
            message = errors.get(key) or "Глава ещё не подготовлена на сервере"
        if raw_status != "done" and key in errors:
            message = errors[key]
        items.append(
            PrepareChapterOut(
                id=key,
                status=status,
                page_count=page_count if status == "done" else 0,
                error=message,
            )
        )
    return PrepareStatusOut(
        manga_id=manga_id,
        total=len(chapters),
        prepared=prepared,
        pending=pending,
        failed=failed,
        batch=batch,
        chapters=items,
        job_id=job_id,
        error=job_error,
    )


# Chapter ids already posted to the media archive in this process.  The media
# endpoint is idempotent, this simply avoids one request per reader page view.
_archive_posted: set[str] = set()
_archive_tasks: set[asyncio.Task] = set()


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
    genres: str | None = Query(default=None, max_length=500),
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
    if genres:
        params["genres"] = genres
    if year:
        params["year"] = year
    if status:
        params["status"] = status
    return await catalog.manga_list(params)


@router.get("/home/updates", response_model=HomeUpdatesOut)
async def home_updates(
    request: Request,
    limit: int = Query(default=25, ge=1, le=50),
) -> HomeUpdatesOut:
    catalog, _, _, _ = clients(request)
    return await catalog.home_updates(limit)


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


async def _run_prepare_job(
    media: MediaClient,
    catalog: CatalogClient,
    job: _PrepareJob,
    chapters: list[ChapterOut],
) -> None:
    """Queue media archiving for chapters that are not prepared yet."""

    try:
        summary_items = await media.archive_summary(list(job.chapter_ids))
    except Exception as exc:
        logger.warning("prepare summary failed for %s: %s", job.manga_id, exc)
        job.error = f"Не удалось получить состояние архивов: {exc}"[:300]
        return

    states: dict[str, str] = {}
    for item in summary_items:
        chapter_id = item.get("chapter_id")
        if isinstance(chapter_id, str):
            states[chapter_id] = str(item.get("status") or "missing")

    semaphore = asyncio.Semaphore(2)

    async def one(chapter: ChapterOut) -> None:
        key = str(chapter.id)
        # Done chapters are never refetched; pending ones already have a
        # media worker.  Failed/missing chapters are safely re-queued.
        if states.get(key) in {"done", "pending"}:
            return
        async with semaphore:
            try:
                chapter_detail = await catalog.chapter(key)
                if not chapter_detail.pages:
                    job.errors[key] = "Источник не отдал страницы главы"
                    return
                result = await media.archive_chapter(
                    {
                        "chapter_id": key,
                        "source": chapter_detail.source,
                        "translator": getattr(chapter_detail, "translator", None),
                        "pages": [
                            {
                                "number": page.number,
                                "url": page.url,
                                "width": page.width,
                                "height": page.height,
                            }
                            for page in chapter_detail.pages
                        ],
                    }
                )
                if isinstance(result, dict) and result.get("status") == "failed":
                    job.errors[key] = str(result.get("error") or "Архивирование не удалось")
            except Exception as exc:
                job.errors[key] = str(exc)[:300]
                logger.debug("prepare chapter failed %s: %s", chapter.id, exc)

    await asyncio.gather(*(one(chapter) for chapter in chapters))


def _prepare_start_payload(job: _PrepareJob) -> PrepareStartOut:
    return PrepareStartOut(
        job_id=job.job_id,
        total=len(job.chapter_ids),
        chapter_ids=list(job.chapter_ids),
    )


async def _start_prepare(request: Request, manga_id: uuid.UUID) -> tuple[PrepareStartOut, bool]:
    catalog, _, _, media = clients(request)
    manga_key = str(manga_id)
    active = _prepare_registry.active(manga_key)
    if active is not None:
        return _prepare_start_payload(active), False

    detail = await catalog.manga(manga_key)
    chapters = [chapter for chapter in detail.chapters if not chapter.is_external]
    chapter_ids = [str(chapter.id) for chapter in chapters]
    if not chapter_ids:
        return PrepareStartOut(job_id=str(uuid.uuid4()), total=0, chapter_ids=[]), False

    async def runner(job: _PrepareJob) -> None:
        await _run_prepare_job(media, catalog, job, chapters)

    job, created = _prepare_registry.start(manga_key, chapter_ids, runner)
    return _prepare_start_payload(job), created


@router.post("/manga/{manga_id}/prepare", response_model=PrepareStartOut)
async def prepare_manga(
    request: Request,
    manga_id: uuid.UUID,
    response: Response,
    user: UserClaims = Depends(require_user),
) -> PrepareStartOut:
    """Queue server-side archiving for every chapter of a title.

    Idempotent while a prepare worker is active: repeated calls return the same
    ``job_id``.  Progress is read back from the persistent media archive via
    :func:`prepare_status`.
    """

    result, created = await _start_prepare(request, manga_id)
    response.status_code = 202 if created else 200
    return result


@router.get("/manga/{manga_id}/prepare", response_model=PrepareStatusOut)
async def prepare_status(
    request: Request,
    manga_id: uuid.UUID,
    user: UserClaims = Depends(require_user),
) -> PrepareStatusOut:
    """Persistent prepare progress for a title.

    Statuses come from the media archive database, so they survive gateway and
    client restarts.  ``batch`` is the first up-to-five prepared chapter ids in
    catalog order and is informational; clients decide which prepared ids they
    still need to download locally.
    """

    catalog, _, _, media = clients(request)
    manga_key = str(manga_id)
    detail = await catalog.manga(manga_key)
    chapters = [chapter for chapter in detail.chapters if not chapter.is_external]
    job = _prepare_registry.active(manga_key)
    summary: dict[str, dict[str, Any]] = {}
    if chapters:
        try:
            items = await media.archive_summary([str(chapter.id) for chapter in chapters])
        except Exception as exc:
            logger.warning("prepare status summary failed for %s: %s", manga_id, exc)
            if job is not None:
                job.error = f"Не удалось получить состояние архивов: {exc}"[:300]
            raise UpstreamError("Не удалось получить состояние подготовки глав") from exc
        for item in items:
            chapter_id = item.get("chapter_id")
            if isinstance(chapter_id, str):
                summary[chapter_id] = item
    return _build_prepare_status(
        manga_key,
        chapters,
        summary,
        active=job is not None,
        job_errors=job.errors if job is not None else None,
        job_error=job.error if job is not None else None,
        job_id=job.job_id if job is not None else None,
    )


@router.post("/manga/{manga_id}/warm")
async def warm_manga(
    request: Request,
    manga_id: uuid.UUID,
    response: Response,
    user: UserClaims = Depends(require_user),
) -> dict[str, Any]:
    """Backward-compatible alias for ``/prepare``."""

    result, created = await _start_prepare(request, manga_id)
    response.status_code = 202 if created else 200
    return {
        "queued": result.total,
        "manga_id": str(manga_id),
        "job_id": result.job_id,
        "chapter_ids": result.chapter_ids,
    }


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


_READER_IMAGE_WIDTH = 1280
_MIN_READER_IMAGE_WIDTH = 320
_MAX_READER_IMAGE_WIDTH = 1600


@router.get("/chapters/{chapter_id}/images/{number}")
async def chapter_image(
    request: Request,
    chapter_id: uuid.UUID,
    number: int,
    w: int | None = Query(default=None),
) -> StreamingResponse:
    catalog, _, _, media = clients(request)
    # Reader pages are downscaled to WebP by the media service.  Archives keep
    # the original bytes; only this reader-facing upstream request asks for a
    # variant.  Clients may request a different width within safe bounds.
    width = _READER_IMAGE_WIDTH if w is None else max(
        _MIN_READER_IMAGE_WIDTH, min(_MAX_READER_IMAGE_WIDTH, w)
    )
    # Prefer the server-side archive: a chapter fetched by any user once is
    # served from media without touching the original source again.
    response = await media.stream(
        f"/internal/archives/chapters/{chapter_id}/pages/{number}",
        params={"w": width},
    )
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
        response = await media.stream(
            "/internal/image", params={"url": page.url, "w": width}
        )
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
        "comments": getattr(state, "comments", None),
    }
    mapping = {code: value for code, value in mapping.items() if value is not None}
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


@router.get("/admin/catalogue")
async def admin_catalogue(
    request: Request, user: UserClaims = Depends(require_admin)
) -> dict[str, Any]:
    catalog, _, _, _ = clients(request)
    return {
        "stats": await catalog.stats(),
        "enrichment": await catalog.enrichment_stats(),
        "crawl_states": await catalog.crawl_states(),
    }


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


class SourceCookieIn(BaseModel):
    cookie: str = Field(default="", max_length=20000)


@router.get("/admin/sources/{code}/cookie")
async def admin_get_source_cookie(
    request: Request,
    code: str,
    user: UserClaims = Depends(require_admin),
) -> dict[str, Any]:
    """Return only the non-secret cookie state for a source."""

    return await request.app.state.parser.request(
        "GET", f"/internal/sources/{quote(code, safe='')}/cookie"
    )


@router.put("/admin/sources/{code}/cookie")
async def admin_put_source_cookie(
    request: Request,
    code: str,
    payload: SourceCookieIn,
    user: UserClaims = Depends(require_admin),
) -> dict[str, Any]:
    """Store or clear a source cookie without ever echoing its value."""

    return await request.app.state.parser.request(
        "PUT",
        f"/internal/sources/{quote(code, safe='')}/cookie",
        json={"cookie": payload.cookie},
    )


_MAX_HAR_BYTES = 50 * 1024 * 1024
_HAR_SOURCE_HOSTS: dict[str, tuple[str, ...]] = {
    "remanga": ("remanga.org",),
    "mangalib": ("mangalib.me", "mangalib.org"),
    "mangapoisk": ("mangapoisk.me", "mangapoisk.org", "mangapoisk.ru"),
    "mangadex": ("mangadex.org",),
    "readmanga": ("readmanga.live",),
}


def _extract_har_cookie(payload: Any, code: str) -> str | None:
    """Find the most complete Cookie header for a source inside a HAR file."""

    if not isinstance(payload, dict):
        return None
    log = payload.get("log")
    if not isinstance(log, dict):
        return None
    entries = log.get("entries")
    if not isinstance(entries, list):
        return None

    hosts = _HAR_SOURCE_HOSTS.get(code, ())
    candidates: list[str] = []
    source_host_hits: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        request_data = entry.get("request")
        if not isinstance(request_data, dict):
            continue
        url = request_data.get("url")
        host = (urlparse(url).hostname or "").lower() if isinstance(url, str) else ""
        headers = request_data.get("headers")
        if not isinstance(headers, list):
            continue
        cookie = ""
        for header in headers:
            if not isinstance(header, dict):
                continue
            if str(header.get("name", "")).lower() != "cookie":
                continue
            value = str(header.get("value", "")).strip()
            if value:
                cookie = value
                break
        if not cookie:
            continue
        candidates.append(cookie)
        if hosts and any(host == item or host.endswith("." + item) for item in hosts):
            source_host_hits.append(cookie)

    if hosts:
        if not source_host_hits:
            return None
        candidates = source_host_hits
    if not candidates:
        return None
    if code == "remanga":
        preferred = [item for item in candidates if "auth:token" in item]
        if preferred:
            candidates = preferred
    return max(candidates, key=len)


@router.post("/admin/sources/{code}/cookie/har")
async def admin_import_source_cookie_har(
    request: Request,
    code: str,
    file: UploadFile = File(...),
    user: UserClaims = Depends(require_admin),
) -> dict[str, Any]:
    """Extract and store a source cookie from an uploaded browser HAR file."""

    raw = await file.read(_MAX_HAR_BYTES + 1)
    if len(raw) > _MAX_HAR_BYTES:
        raise ValidationError("HAR-файл слишком большой (максимум 50 МБ)", code="har_too_large")
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValidationError("Файл не является корректным HAR", code="har_invalid") from exc
    cookie = _extract_har_cookie(payload, code)
    if not cookie:
        raise ValidationError(
            "В HAR не найдены cookie для этого источника. Откройте сайт источника, авторизуйтесь и сохраните HAR заново.",
            code="har_cookie_not_found",
        )
    return await request.app.state.parser.request(
        "PUT",
        f"/internal/sources/{quote(code, safe='')}/cookie",
        json={"cookie": cookie},
    )



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
