from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import FileResponse
from manga_common.errors import NotFoundError, ValidationError
from manga_common.schemas import ExportJobOut, OkResponse
from manga_common.security import require_internal_token
from pydantic import BaseModel

from .archive import (
    ArchiveManager,
    ArchiveRequest,
    ArchiveState,
    ArchiveStats,
    ArchiveSummary,
)
from .cache import (
    MediaCache,
    MediaCacheStats,
    resolve_width,
    usage_level,
    usage_percent,
)
from .exporter import ExportManager, ExportRequest

router = APIRouter(prefix="/internal", dependencies=[Depends(require_internal_token)])

_IMAGE_HEADERS = {
    "Cache-Control": "public, max-age=86400, stale-while-revalidate=604800",
    "X-Content-Type-Options": "nosniff",
}


def get_cache(request: Request) -> MediaCache:
    return request.app.state.cache


def get_exports(request: Request) -> ExportManager:
    return request.app.state.exports


def get_archives(request: Request) -> ArchiveManager:
    return request.app.state.archives


class ImageCacheStatsOut(BaseModel):
    used_bytes: int
    cap_bytes: int
    files: int
    evictions: int
    last_pruned_at: datetime | None
    usage_percent: float
    level: Literal["ok", "warning", "critical", "unbounded"]


class ArchiveStatsOut(BaseModel):
    total: int
    done: int
    failed: int
    pending: int
    done_bytes: int
    db_bytes: int
    cap_bytes: int
    evictions: int
    last_pruned_at: datetime | None
    usage_percent: float
    level: Literal["ok", "warning", "critical", "unbounded"]


class MediaStatsOut(BaseModel):
    generated_at: datetime
    image_cache: ImageCacheStatsOut
    archives: ArchiveStatsOut
    warnings: list[str]


class PruneResultOut(BaseModel):
    removed: int
    freed_bytes: int
    used_bytes: int
    cap_bytes: int
    dry_run: bool


class MaintenancePruneOut(BaseModel):
    dry_run: bool
    image_cache: PruneResultOut
    archives: PruneResultOut


def _image_stats_payload(stats: MediaCacheStats) -> ImageCacheStatsOut:
    return ImageCacheStatsOut(
        used_bytes=stats.used_bytes,
        cap_bytes=stats.cap_bytes,
        files=stats.files,
        evictions=stats.evictions,
        last_pruned_at=stats.last_pruned_at,
        usage_percent=stats.usage_percent,
        level=stats.level,  # type: ignore[arg-type]
    )


def _archive_stats_payload(stats: ArchiveStats, cap_bytes: int) -> ArchiveStatsOut:
    return ArchiveStatsOut(
        total=stats.total,
        done=stats.done,
        failed=stats.failed,
        pending=stats.pending,
        done_bytes=stats.done_bytes,
        db_bytes=stats.db_bytes,
        cap_bytes=cap_bytes,
        evictions=stats.evictions,
        last_pruned_at=stats.last_pruned_at,
        usage_percent=usage_percent(stats.done_bytes, cap_bytes),
        level=usage_level(stats.done_bytes, cap_bytes),  # type: ignore[arg-type]
    )


def _storage_warnings(
    image: ImageCacheStatsOut, archives: ArchiveStatsOut
) -> list[str]:
    warnings: list[str] = []
    if image.level == "critical":
        warnings.append(
            f"Кэш изображений заполнен на {image.usage_percent:.1f}% — LRU удаляет старые файлы"
        )
    elif image.level == "warning":
        warnings.append(
            f"Кэш изображений заполнен на {image.usage_percent:.1f}% — приближается к лимиту"
        )
    if archives.level == "critical":
        warnings.append(
            f"Архив глав заполнен на {archives.usage_percent:.1f}% — LRU удаляет старые главы"
        )
    elif archives.level == "warning":
        warnings.append(
            f"Архив глав заполнен на {archives.usage_percent:.1f}% — приближается к лимиту"
        )
    return warnings


@router.get("/stats", response_model=MediaStatsOut)
async def stats(
    cache: MediaCache = Depends(get_cache),
    archives: ArchiveManager = Depends(get_archives),
) -> MediaStatsOut:
    image_stats = _image_stats_payload(await cache.stats())
    archive_stats = _archive_stats_payload(await archives.stats(), archives.max_bytes)
    return MediaStatsOut(
        generated_at=datetime.now(UTC),
        image_cache=image_stats,
        archives=archive_stats,
        warnings=_storage_warnings(image_stats, archive_stats),
    )


@router.post("/maintenance/prune", response_model=MaintenancePruneOut)
async def prune_storage(
    dry_run: bool = Query(
        default=True,
        description="Only report what would be evicted. Set false to delete.",
    ),
    cache: MediaCache = Depends(get_cache),
    archives: ArchiveManager = Depends(get_archives),
) -> MaintenancePruneOut:
    """Run both LRU sweeps.

    Destructive calls stay behind the internal token and require an explicit
    ``dry_run=false``; the default is a read-only report.
    """

    image_result = await cache.prune(dry_run=dry_run)
    archive_result = await archives.prune(dry_run=dry_run)
    return MaintenancePruneOut(
        dry_run=dry_run,
        image_cache=PruneResultOut(
            removed=image_result.removed,
            freed_bytes=image_result.freed_bytes,
            used_bytes=image_result.used_bytes,
            cap_bytes=image_result.cap_bytes,
            dry_run=image_result.dry_run,
        ),
        archives=PruneResultOut(
            removed=archive_result.removed,
            freed_bytes=archive_result.freed_bytes,
            used_bytes=archive_result.used_bytes,
            cap_bytes=archive_result.cap_bytes,
            dry_run=archive_result.dry_run,
        ),
    )


@router.get("/image")
async def image(
    url: str = Query(min_length=8, max_length=4096),
    referer: str | None = Query(default=None, max_length=4096),
    w: int | None = Query(default=None, ge=320, le=1600),
    cache: MediaCache = Depends(get_cache),
) -> FileResponse:
    media = await cache.get(url, referer=referer, width=resolve_width(w))
    return FileResponse(
        media.path,
        media_type=media.content_type,
        headers={
            **_IMAGE_HEADERS,
            "ETag": f'"{media.etag}"',
        },
    )


@router.get("/archives/chapters/summary", response_model=ArchiveSummary)
async def archives_summary(
    ids: str = Query(default="", max_length=16384),
    archives: ArchiveManager = Depends(get_archives),
) -> ArchiveSummary:
    """Batch status feed for prepared chapters.

    ``ids`` is a comma-separated list; unknown chapters come back as
    ``missing`` instead of a 404 so a caller can poll a mixed batch.
    """

    raw = [part.strip() for part in ids.split(",") if part.strip()]
    if len(raw) > 500:
        raise ValidationError("За один запрос можно проверить не более 500 глав")
    chapter_ids: list[uuid.UUID] = []
    for value in raw:
        try:
            chapter_ids.append(uuid.UUID(value))
        except ValueError as exc:
            raise ValidationError("Некорректный идентификатор главы") from exc
    return ArchiveSummary(items=await archives.summary(chapter_ids))


@router.post("/archives/chapters", response_model=ArchiveState)
async def archive_chapter(
    payload: ArchiveRequest,
    response: Response,
    archives: ArchiveManager = Depends(get_archives),
) -> ArchiveState:
    state, created = await archives.create(payload)
    response.status_code = 202 if created else 200
    return state


@router.get("/archives/chapters/{chapter_id}", response_model=ArchiveState)
async def archive_status(
    chapter_id: uuid.UUID,
    archives: ArchiveManager = Depends(get_archives),
) -> ArchiveState:
    state = await archives.metadata(chapter_id)
    if state is None:
        raise NotFoundError("Архив главы не найден")
    return state


@router.get("/archives/chapters/{chapter_id}/pages/{number}")
async def archive_page(
    chapter_id: uuid.UUID,
    number: int,
    w: int | None = Query(default=None, ge=320, le=1600),
    cache: MediaCache = Depends(get_cache),
    archives: ArchiveManager = Depends(get_archives),
) -> Response:
    page = await archives.page(chapter_id, number)
    if page is None:
        raise NotFoundError("Страница не найдена в архиве")
    width = resolve_width(w)
    if width is not None:
        variant = await cache.variant_from_bytes(page.data, page.content_type, width)
        if variant is not None:
            return FileResponse(
                variant.path,
                media_type=variant.content_type,
                headers={
                    **_IMAGE_HEADERS,
                    "ETag": f'"{variant.etag}"',
                },
            )
    return Response(
        content=page.data,
        media_type=page.content_type,
        headers=_IMAGE_HEADERS,
    )


@router.delete("/archives/chapters/{chapter_id}", response_model=OkResponse)
async def delete_archive(
    chapter_id: uuid.UUID,
    archives: ArchiveManager = Depends(get_archives),
) -> OkResponse:
    if not await archives.delete(chapter_id):
        raise NotFoundError("Архив главы не найден")
    return OkResponse(message="Архив главы удалён")


@router.post("/exports", response_model=ExportJobOut)
async def create_export(
    payload: ExportRequest,
    exports: ExportManager = Depends(get_exports),
) -> ExportJobOut:
    return await exports.create(payload)


@router.get("/exports/{job_id}", response_model=ExportJobOut)
async def export_status(
    job_id: uuid.UUID,
    exports: ExportManager = Depends(get_exports),
) -> ExportJobOut:
    return await exports.get(job_id)


@router.get("/exports/{job_id}/download")
async def export_download(
    job_id: uuid.UUID,
    exports: ExportManager = Depends(get_exports),
) -> FileResponse:
    path, filename = await exports.download(job_id)
    media_type = "application/pdf" if path.suffix == ".pdf" else "application/zip"
    return FileResponse(path, media_type=media_type, filename=filename)


@router.delete("/exports/{job_id}", response_model=OkResponse)
async def delete_export(
    job_id: uuid.UUID,
    exports: ExportManager = Depends(get_exports),
) -> OkResponse:
    await exports.delete(job_id)
    return OkResponse(message="Экспорт удалён")


@router.post("/maintenance/cleanup", response_model=OkResponse)
async def cleanup(
    exports: ExportManager = Depends(get_exports),
) -> OkResponse:
    removed = await exports.cleanup()
    return OkResponse(message=f"Удалено экспортов: {removed}")
