from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import FileResponse
from manga_common.errors import NotFoundError, ValidationError
from manga_common.schemas import ExportJobOut, OkResponse
from manga_common.security import require_internal_token

from .archive import ArchiveManager, ArchiveRequest, ArchiveState, ArchiveSummary
from .cache import MediaCache, resolve_width
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
