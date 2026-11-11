from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from manga_common.schemas import ExportJobOut, OkResponse
from manga_common.security import require_internal_token

from .cache import MediaCache
from .exporter import ExportManager, ExportRequest

router = APIRouter(prefix="/internal", dependencies=[Depends(require_internal_token)])


def get_cache(request: Request) -> MediaCache:
    return request.app.state.cache


def get_exports(request: Request) -> ExportManager:
    return request.app.state.exports


@router.get("/image")
async def image(
    url: str = Query(min_length=8, max_length=4096),
    referer: str | None = Query(default=None, max_length=4096),
    cache: MediaCache = Depends(get_cache),
) -> FileResponse:
    media = await cache.get(url, referer=referer)
    return FileResponse(
        media.path,
        media_type=media.content_type,
        headers={
            "Cache-Control": "public, max-age=86400, stale-while-revalidate=604800",
            "ETag": f'"{media.etag}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


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
