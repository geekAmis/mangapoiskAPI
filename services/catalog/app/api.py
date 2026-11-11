from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from manga_common.schemas import ChapterOut, MangaListResponse, MangaOut, SourceOut
from manga_common.security import require_internal_token
from manga_common.source_models import MangaDetail, MangaSummary, SourceInfo

from .schemas import (
    CatalogStats,
    ChapterDetailInternal,
    ImportRequest,
    ImportResult,
    PagesPatch,
    RefreshResult,
    SourceSyncRequest,
)
from .service import CatalogService

router = APIRouter(prefix="/internal", dependencies=[Depends(require_internal_token)])


def get_service(request: Request) -> CatalogService:
    return request.app.state.service


@router.get("/sources", response_model=list[SourceOut])
async def sources(
    service: CatalogService = Depends(get_service),
) -> list[SourceOut]:
    from .repository import list_sources

    async with service.session_factory() as session:
        rows = await list_sources(session)
        return [
            SourceOut(
                code=row.code,
                name=row.name,
                base_url=row.base_url,
                language=row.language,
                enabled=row.enabled,
                requires_cookies=row.requires_cookies,
                capabilities=row.capabilities or {},
            )
            for row in rows
        ]


@router.post("/sources/sync")
async def sync_sources(
    payload: SourceSyncRequest,
    service: CatalogService = Depends(get_service),
) -> dict[str, int]:
    infos = [SourceInfo.model_validate(item) for item in payload.sources]
    count = await service.sync_sources(infos)
    return {"synced": count}


@router.get("/manga", response_model=MangaListResponse)
async def manga_list(
    query: str | None = Query(default=None, max_length=200),
    source: str | None = Query(default=None, max_length=64),
    genre: str | None = Query(default=None, max_length=64),
    year: int | None = Query(default=None, ge=1900, le=2100),
    status: str | None = Query(default=None, max_length=64),
    sort: str = Query(default="popular", pattern="^(popular|rating|updated|title|new)$"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=24, ge=1, le=100),
    service: CatalogService = Depends(get_service),
) -> MangaListResponse:
    return await service.list(
        query=query,
        source=source,
        genre=genre,
        year=year,
        status=status,
        sort=sort,
        page=page,
        limit=limit,
    )


@router.get("/manga/search", response_model=MangaListResponse)
async def manga_search(
    q: str = Query(min_length=1, max_length=200),
    source: str | None = Query(default=None, max_length=64),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=24, ge=1, le=100),
    service: CatalogService = Depends(get_service),
) -> MangaListResponse:
    return await service.list(query=q, source=source, page=page, limit=limit)


@router.get("/manga/by-source/{source}/{source_id}", response_model=dict)
async def manga_by_source(
    source: str,
    source_id: str,
    service: CatalogService = Depends(get_service),
) -> dict:
    detail = await service.manga_by_source(source, source_id)
    return detail.model_dump(mode="json")


@router.get("/manga/{manga_id}")
async def manga_detail(
    manga_id: uuid.UUID,
    service: CatalogService = Depends(get_service),
) -> dict:
    detail = await service.manga_detail(manga_id)
    return detail.model_dump(mode="json")


@router.post("/manga/import", response_model=ImportResult)
async def import_manga(
    payload: ImportRequest,
    service: CatalogService = Depends(get_service),
) -> ImportResult:
    return await service.import_from_source(
        payload.source, source_id=payload.source_id, url=payload.url
    )


@router.post("/manga/import-detail", response_model=ImportResult)
async def import_manga_detail(
    payload: MangaDetail,
    service: CatalogService = Depends(get_service),
) -> ImportResult:
    return await service.import_detail(payload)


@router.post("/manga/import-summary", response_model=MangaOut)
async def import_manga_summary(
    payload: MangaSummary,
    service: CatalogService = Depends(get_service),
) -> MangaOut:
    return await service.import_summary(payload)


@router.get("/manga/{manga_id}/chapters", response_model=list[ChapterOut])
async def manga_chapters(
    manga_id: uuid.UUID,
    query: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=200, ge=1, le=500),
    service: CatalogService = Depends(get_service),
) -> list[ChapterOut]:
    return await service.chapters(manga_id, query=query, page=page, limit=limit)


@router.get("/chapters/{chapter_id}/meta", response_model=ChapterOut)
async def chapter_meta(
    chapter_id: uuid.UUID,
    service: CatalogService = Depends(get_service),
) -> ChapterOut:
    return await service.chapter_meta(chapter_id)


@router.get("/chapters/{chapter_id}", response_model=ChapterDetailInternal)
async def chapter_detail(
    chapter_id: uuid.UUID,
    refresh: bool = Query(default=True),
    service: CatalogService = Depends(get_service),
) -> ChapterDetailInternal:
    return await service.chapter_detail(chapter_id, refresh=refresh)


@router.patch("/chapters/{chapter_id}/pages", response_model=ChapterDetailInternal)
async def patch_chapter_pages(
    chapter_id: uuid.UUID,
    payload: PagesPatch,
    service: CatalogService = Depends(get_service),
) -> ChapterDetailInternal:
    from manga_common.errors import NotFoundError

    from .repository import get_chapter, update_chapter_pages

    async with service.session_factory() as session:
        chapter = await get_chapter(session, chapter_id)
        if chapter is None:
            raise NotFoundError("Chapter not found")
        await update_chapter_pages(
            session, chapter, payload.pages, is_horizontal=payload.is_horizontal
        )
        await session.commit()
    return await service.chapter_detail(chapter_id, refresh=False)


@router.post("/maintenance/refresh", response_model=RefreshResult)
async def maintenance_refresh(
    limit: int = Query(default=5, ge=1, le=50),
    service: CatalogService = Depends(get_service),
) -> RefreshResult:
    return await service.refresh_stale(limit)


@router.get("/stats", response_model=CatalogStats)
async def catalog_stats(
    service: CatalogService = Depends(get_service),
) -> CatalogStats:
    return await service.catalog_stats()


@router.get("/manga/{manga_id}/exists")
async def manga_exists(
    manga_id: uuid.UUID,
    service: CatalogService = Depends(get_service),
) -> dict[str, bool]:
    from .repository import find_manga

    async with service.session_factory() as session:
        return {"exists": await find_manga(session, manga_id) is not None}
