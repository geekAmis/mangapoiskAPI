from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from manga_common.schemas import (
    ChapterOut,
    CollectionAuditOut,
    CollectionListOut,
    CollectionOut,
    MangaListResponse,
    MangaOut,
    MangaVariantsOut,
    RelatedMangaOut,
    SitemapEntryOut,
    SourceOut,
    SuggestResponse,
)
from manga_common.security import require_internal_token
from manga_common.source_models import MangaDetail, MangaSummary, SourceInfo

from .schemas import (
    CatalogStats,
    ChapterDetailInternal,
    CollectionCreate,
    CollectionItemIn,
    CollectionOrderIn,
    CollectionUpdate,
    CrawlStateIn,
    CrawlStateOut,
    EnrichmentFailureRequest,
    EnrichmentStats,
    GenreListOut,
    HomeUpdatesOut,
    ImportRequest,
    ImportResult,
    PagesPatch,
    PendingEnrichmentListOut,
    RecommendationRequest,
    RecommendationResult,
    RefreshResult,
    RelationsIn,
    RelationsOut,
    SearchBackfillStats,
    SourceSyncRequest,
)
from .service import CatalogService

router = APIRouter(prefix="/internal", dependencies=[Depends(require_internal_token)])


def get_service(request: Request) -> CatalogService:
    return request.app.state.service


def _parse_ids(raw: str | None, *, limit: int = 100) -> list[uuid.UUID]:
    result: list[uuid.UUID] = []
    for chunk in (raw or "").split(","):
        value = chunk.strip()
        if not value:
            continue
        try:
            parsed = uuid.UUID(value)
        except ValueError:
            continue
        if parsed not in result:
            result.append(parsed)
        if len(result) >= limit:
            break
    return result


@router.get("/collections", response_model=CollectionListOut)
async def collections(
    limit: int = Query(default=12, ge=1, le=24),
    service: CatalogService = Depends(get_service),
) -> CollectionListOut:
    return await service.collections(limit=limit)


@router.get("/collections/{slug}", response_model=CollectionOut)
async def collection(
    slug: str,
    limit: int = Query(default=24, ge=1, le=60),
    service: CatalogService = Depends(get_service),
) -> CollectionOut:
    return await service.collection(slug, limit=limit)


@router.get("/admin/collections", response_model=CollectionListOut)
async def admin_collections(
    service: CatalogService = Depends(get_service),
) -> CollectionListOut:
    return await service.admin_collections()


@router.post("/admin/collections", response_model=CollectionOut)
async def admin_create_collection(
    payload: CollectionCreate,
    service: CatalogService = Depends(get_service),
) -> CollectionOut:
    return await service.create_collection(payload)


@router.patch("/admin/collections/{collection_id}", response_model=CollectionOut)
async def admin_update_collection(
    collection_id: uuid.UUID,
    payload: CollectionUpdate,
    service: CatalogService = Depends(get_service),
) -> CollectionOut:
    return await service.update_collection(collection_id, payload)


@router.delete("/admin/collections/{collection_id}")
async def admin_delete_collection(
    collection_id: uuid.UUID,
    service: CatalogService = Depends(get_service),
) -> dict[str, bool]:
    await service.delete_collection(collection_id)
    return {"ok": True}


@router.post("/admin/collections/{collection_id}/items", response_model=CollectionOut)
async def admin_add_collection_item(
    collection_id: uuid.UUID,
    payload: CollectionItemIn,
    service: CatalogService = Depends(get_service),
) -> CollectionOut:
    return await service.add_collection_item(collection_id, payload)


@router.delete(
    "/admin/collections/{collection_id}/items/{manga_id}", response_model=CollectionOut
)
async def admin_remove_collection_item(
    collection_id: uuid.UUID,
    manga_id: uuid.UUID,
    service: CatalogService = Depends(get_service),
) -> CollectionOut:
    return await service.remove_collection_item(collection_id, manga_id)


@router.put("/admin/collections/{collection_id}/order", response_model=CollectionOut)
async def admin_reorder_collection(
    collection_id: uuid.UUID,
    payload: CollectionOrderIn,
    service: CatalogService = Depends(get_service),
) -> CollectionOut:
    return await service.reorder_collection_items(collection_id, payload)


@router.get("/admin/collections/audit", response_model=list[CollectionAuditOut])
async def admin_collection_audit(
    limit: int = Query(default=100, ge=1, le=500),
    service: CatalogService = Depends(get_service),
) -> list[CollectionAuditOut]:
    return await service.collection_audit(limit=limit)


@router.get("/sources", response_model=list[SourceOut])
async def sources(
    service: CatalogService = Depends(get_service),
) -> list[SourceOut]:
    rows = await service.source_rows()
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


@router.get("/sitemap", response_model=list[SitemapEntryOut])
async def sitemap(
    limit: int = Query(default=50_000, ge=1, le=50_000),
    service: CatalogService = Depends(get_service),
) -> list[SitemapEntryOut]:
    """One row per canonical title for the gateway sitemap collector."""

    return await service.sitemap_entries(limit=limit)


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
    genres: str | None = Query(
        default=None,
        max_length=500,
        description="AND filter: horror+fantasy+mecha (canonical English slugs)",
    ),
    year: int | None = Query(default=None, ge=1900, le=2100),
    status: str | None = Query(default=None, max_length=64),
    include_empty: bool = Query(default=False),
    sort: str = Query(default="popular", pattern="^(popular|rating|updated|title|new)$"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=24, ge=1, le=100),
    service: CatalogService = Depends(get_service),
) -> MangaListResponse:
    from .normalization import parse_genre_filter

    return await service.list(
        query=query,
        source=source,
        genre=genre,
        genres=parse_genre_filter(genres),
        year=year,
        status=status,
        include_empty=include_empty,
        sort=sort,
        page=page,
        limit=limit,
    )


@router.get("/manga/suggest", response_model=SuggestResponse)
async def manga_suggest(
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=6, ge=1, le=12),
    service: CatalogService = Depends(get_service),
) -> SuggestResponse:
    """Local-only instant suggestions.  Kept separate from live search."""

    return await service.suggest(q, limit=limit)


@router.get("/manga/search", response_model=MangaListResponse)
async def manga_search(
    q: str = Query(min_length=1, max_length=200),
    source: str | None = Query(default=None, max_length=64),
    genre: str | None = Query(default=None, max_length=64),
    genres: str | None = Query(default=None, max_length=500),
    include_empty: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=24, ge=1, le=100),
    service: CatalogService = Depends(get_service),
) -> MangaListResponse:
    from .normalization import parse_genre_filter

    return await service.list(
        query=q,
        source=source,
        genre=genre,
        genres=parse_genre_filter(genres),
        include_empty=include_empty,
        page=page,
        limit=limit,
    )


@router.get("/manga/by-source/{source}/{source_id}", response_model=dict)
async def manga_by_source(
    source: str,
    source_id: str,
    service: CatalogService = Depends(get_service),
) -> dict:
    detail = await service.manga_by_source(source, source_id)
    return detail.model_dump(mode="json")


@router.get("/manga/pending", response_model=PendingEnrichmentListOut)
async def pending_enrichment(
    source: str = Query(min_length=1, max_length=64),
    limit: int = Query(default=50, ge=1, le=500),
    service: CatalogService = Depends(get_service),
) -> PendingEnrichmentListOut:
    return await service.pending_enrichment(source=source, limit=limit)


@router.get("/enrichment/stats", response_model=EnrichmentStats)
async def enrichment_stats(
    rate_per_minute: int = Query(default=36, ge=1, le=600),
    requests_per_title: int = Query(default=2, ge=1, le=10),
    service: CatalogService = Depends(get_service),
) -> EnrichmentStats:
    return await service.enrichment_stats(
        rate_per_minute=rate_per_minute, requests_per_title=requests_per_title
    )


@router.post("/manga/{manga_id}/enrichment-failure")
async def enrichment_failure(
    manga_id: uuid.UUID,
    payload: EnrichmentFailureRequest,
    service: CatalogService = Depends(get_service),
) -> dict:
    return await service.record_enrichment_failure(manga_id, payload)


@router.get("/genres", response_model=GenreListOut)
async def genres(
    service: CatalogService = Depends(get_service),
) -> GenreListOut:
    return await service.genres()


@router.get("/home/updates", response_model=HomeUpdatesOut)
async def home_updates(
    limit: int = Query(default=25, ge=1, le=100),
    service: CatalogService = Depends(get_service),
) -> HomeUpdatesOut:
    return await service.home_updates(limit=limit)


@router.post("/recommendations", response_model=RecommendationResult)
async def recommendations(
    payload: RecommendationRequest,
    service: CatalogService = Depends(get_service),
) -> RecommendationResult:
    return await service.recommendations(payload)


@router.get("/manga/{manga_id}/related", response_model=RelatedMangaOut)
async def related_manga(
    manga_id: uuid.UUID,
    history: str | None = Query(
        default=None,
        max_length=4096,
        description="Comma-separated read manga ids used to exclude already-read titles",
    ),
    limit: int = Query(default=12, ge=6, le=12),
    service: CatalogService = Depends(get_service),
) -> RelatedMangaOut:
    return await service.related(
        manga_id,
        history_ids=_parse_ids(history),
        limit=limit,
    )


@router.get("/manga/{manga_id}/similar", response_model=list[MangaOut])
async def similar_manga(
    manga_id: uuid.UUID,
    history: str | None = Query(default=None, max_length=4096),
    limit: int = Query(default=12, ge=6, le=12),
    service: CatalogService = Depends(get_service),
) -> list[MangaOut]:
    return await service.similar(
        manga_id,
        history_ids=_parse_ids(history),
        limit=limit,
    )


@router.put("/manga/{manga_id}/relations", response_model=RelationsOut)
async def link_relations(
    manga_id: uuid.UUID,
    payload: RelationsIn,
    service: CatalogService = Depends(get_service),
) -> RelationsOut:
    return await service.link_relations(manga_id, payload)


@router.get("/crawl-state", response_model=list[CrawlStateOut])
async def crawl_states(
    source: str | None = Query(default=None, max_length=64),
    service: CatalogService = Depends(get_service),
) -> list[CrawlStateOut]:
    return await service.crawl_states(source=source)


@router.get("/crawl-state/{source}", response_model=CrawlStateOut)
async def crawl_state(
    source: str,
    mode: str = Query(
        default="full", pattern="^(full|incremental|health|enrichment)$"
    ),
    service: CatalogService = Depends(get_service),
) -> CrawlStateOut:
    from manga_common.errors import NotFoundError

    state = await service.crawl_state(source, mode)
    if state is None:
        raise NotFoundError("Crawl state not found")
    return state


@router.put("/crawl-state/{source}", response_model=CrawlStateOut)
async def save_crawl_state(
    source: str,
    payload: CrawlStateIn,
    service: CatalogService = Depends(get_service),
) -> CrawlStateOut:
    return await service.save_crawl_state(payload.model_copy(update={"source": source}))


@router.get("/manga/{manga_id}/variants", response_model=MangaVariantsOut)
async def manga_variants(
    manga_id: uuid.UUID,
    service: CatalogService = Depends(get_service),
) -> MangaVariantsOut:
    return await service.variants(manga_id)


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


@router.post("/maintenance/reset-enrichment")
async def maintenance_reset_enrichment(
    source: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=500, ge=1, le=5000),
    service: CatalogService = Depends(get_service),
) -> dict[str, int]:
    return {"queued": await service.reset_enrichment(source=source, limit=limit)}


@router.post("/maintenance/rotate-enrichment")
async def maintenance_rotate_enrichment(
    source: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=500, ge=1, le=5000),
    service: CatalogService = Depends(get_service),
) -> dict[str, int]:
    return {"queued": await service.rotate_enrichment(source=source, limit=limit)}


@router.get("/search/backfill", response_model=SearchBackfillStats)
async def search_backfill(
    service: CatalogService = Depends(get_service),
) -> SearchBackfillStats:
    from manga_common.errors import NotFoundError

    state = await service.search_backfill()
    if state is None:
        raise NotFoundError("Search backfill state not found")
    return state


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
