from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from manga_common.db import retry_on_locked
from manga_common.errors import NotFoundError, UpstreamError
from manga_common.schemas import (
    ChapterOut,
    CollectionAuditOut,
    CollectionListOut,
    CollectionOut,
    CoverOut,
    GenreRefOut,
    MangaDetailOut,
    MangaListResponse,
    MangaOut,
    MangaVariantOut,
    MangaVariantsOut,
    PageOut,
    RelatedMangaOut,
    SearchSuggestionOut,
    SitemapEntryOut,
    SuggestResponse,
    TranslatorOut,
)
from manga_common.source_models import MangaDetail, SourceInfo
from manga_common.text import build_url_slug
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config import CatalogSettings
from .discovery import (
    add_collection_item,
    collection_manga,
    create_collection,
    delete_collection,
    find_collection,
    find_collection_by_slug,
    list_collection_audit,
    list_collections,
    remove_collection_item,
    reorder_collection_items,
    similar_manga,
    update_collection,
)
from .normalization import GENRE_LABELS, genre_slugs
from .parser_client import ParserClient
from .recommendations import (
    clear_discovery_cache as clear_discovery_caches,
)
from .recommendations import (
    collection_cache,
    discovery_cache_key,
    recommendation_cache,
    recommendation_cache_key,
    similar_cache,
)
from .repository import (
    DESCRIPTION_FALLBACK,
    chapter_label,
    covers_for_group,
    enrichment_stats,
    find_manga,
    get_chapter,
    get_crawl_state,
    get_manga_chapters,
    latest_updates,
    list_crawl_states,
    list_genres,
    list_manga,
    list_sources,
    manga_relations,
    ordered_chapter_ids,
    pending_enrichment,
    recommend_manga,
    record_enrichment_failure,
    rotate_enrichment,
    search_backfill_stats,
    stale_manga,
    stats,
    suggest_manga,
    update_chapter_pages,
    upsert_crawl_state,
    upsert_manga_detail,
    upsert_relation,
    upsert_source,
)
from .repository import (
    sitemap_entries as repo_sitemap_entries,
)
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
    GenreOut,
    HomeUpdateOut,
    HomeUpdatesOut,
    ImportResult,
    NewChapterEvent,
    PendingEnrichmentListOut,
    PendingEnrichmentOut,
    RecommendationRequest,
    RecommendationResult,
    RefreshResult,
    RelationsIn,
    RelationsOut,
    SearchBackfillStats,
)
from .search import suggestion_reason

logger = logging.getLogger(__name__)


def _cover_out(cover) -> CoverOut:  # type: ignore[no-untyped-def]
    return CoverOut(
        id=cover.id,
        source=cover.source,
        source_id=cover.source_id,
        url=cover.url,
        rating=cover.rating,
        quality=cover.quality,
        chapters_count=cover.chapters_count,
        updated_at=cover.updated_at,
        is_primary=cover.is_primary,
    )


def _manga_out(manga, covers=None) -> MangaOut:  # type: ignore[no-untyped-def]
    payload = MangaOut.model_validate(manga)
    if not payload.url_slug:
        from .repository import ensure_url_slug

        payload.url_slug = ensure_url_slug(manga)
    payload.description_missing = not bool((manga.description or "").strip())
    payload.description_fallback = DESCRIPTION_FALLBACK if payload.description_missing else None
    payload.genre_slugs = genre_slugs(manga.genres or [])
    payload.genre_details = [
        GenreRefOut(slug=slug, label=GENRE_LABELS.get(slug, slug))
        for slug in payload.genre_slugs
    ]
    if covers is not None:
        payload.covers = [_cover_out(cover) for cover in covers]
    return payload


def _collection_out(collection, rows) -> CollectionOut:  # type: ignore[no-untyped-def]
    return CollectionOut(
        id=collection.id,
        slug=collection.slug,
        title=collection.title,
        description=collection.description or "",
        kind=collection.kind,  # type: ignore[arg-type]
        rule=collection.rule,
        enabled=collection.enabled,
        position=collection.position,
        limit=collection.limit,
        item_count=len(rows),
        items=[_manga_out(row) for row in rows],
        created_at=collection.created_at,
        updated_at=collection.updated_at,
    )


def _crawl_state_out(state) -> CrawlStateOut:  # type: ignore[no-untyped-def]
    return CrawlStateOut(
        id=state.id,
        source=state.source,
        mode=state.mode,
        page=state.page,
        status=state.status,
        last_error=state.last_error,
        next_run_at=state.next_run_at,
        total_pages=state.total_pages,
        items_seen=state.items_seen,
        items_imported=state.items_imported,
        last_run_at=state.last_run_at,
        last_success_at=state.last_success_at,
        failure_count=state.failure_count,
        failure_kind=state.failure_kind,
        eta_seconds=state.eta_seconds,
        created_at=state.created_at,
        updated_at=state.updated_at,
    )


def _chapter_out(chapter) -> ChapterOut:  # type: ignore[no-untyped-def]
    return ChapterOut.model_validate(chapter)


class CatalogService:
    def __init__(
        self,
        settings: CatalogSettings,
        session_factory: async_sessionmaker[AsyncSession],
        parser: ParserClient,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.parser = parser

    async def import_from_source(
        self, source: str, *, source_id: str | None = None, url: str | None = None
    ) -> ImportResult:
        detail = await self.parser.manga(source, source_id=source_id, url=url)
        return await self.import_detail(detail)

    async def import_detail(self, detail: MangaDetail) -> ImportResult:
        async with self.session_factory() as session:
            manga, created, new_chapters = await upsert_manga_detail(session, detail)
            await session.commit()
            clear_discovery_caches()
            chapters = await get_manga_chapters(session, manga.id, limit=2000)
            covers = await covers_for_group(session, manga.group_key)
            manga_out = _manga_out(manga, covers)
            detail_out = MangaDetailOut(
                **manga_out.model_dump(),
                chapters=[_chapter_out(chapter) for chapter in chapters],
            )
            return ImportResult(
                manga=detail_out,
                source=detail.source,
                created=created,
                imported_chapters=len(new_chapters),
                imported_pages=sum(chapter.page_count for chapter in new_chapters),
                new_chapters=[_chapter_out(chapter) for chapter in new_chapters],
            )

    async def import_summary(self, summary) -> MangaOut:  # type: ignore[no-untyped-def]
        from .repository import upsert_manga_summary

        async with self.session_factory() as session:
            manga, _ = await upsert_manga_summary(session, summary)
            await session.commit()
            clear_discovery_caches()
            covers = await covers_for_group(session, manga.group_key)
            return _manga_out(manga, covers)

    async def chapter_meta(self, chapter_id: uuid.UUID) -> ChapterOut:
        async def read() -> ChapterOut:
            async with self.session_factory() as session:
                chapter = await get_chapter(session, chapter_id)
                if chapter is None:
                    raise NotFoundError("Chapter not found")
                return _chapter_out(chapter)

        return await retry_on_locked(read)

    async def variants(self, manga_id: uuid.UUID) -> MangaVariantsOut:
        from .repository import manga_variants

        async def read() -> MangaVariantsOut:
            async with self.session_factory() as session:
                manga = await find_manga(session, manga_id)
                if manga is None:
                    raise NotFoundError("Manga not found")
                rows = await manga_variants(session, manga)
                return MangaVariantsOut(
                    primary_id=manga.id,
                    items=[
                        MangaVariantOut(
                            id=row["id"],
                            title=row["title"],
                            source=row["source"],
                            source_id=row["source_id"],
                            poster_url=row["poster_url"],
                            rating=row["rating"],
                            chapters_count=row["chapters_count"],
                            translators=[
                                TranslatorOut(name=item["name"], count=item["count"])
                                for item in row["translators"]
                            ],
                        )
                        for row in rows
                    ],
                )

        return await retry_on_locked(read)

    async def manga_detail(self, manga_id: uuid.UUID) -> MangaDetailOut:
        async def read() -> MangaDetailOut:
            async with self.session_factory() as session:
                manga = await find_manga(session, manga_id)
                if manga is None:
                    raise NotFoundError("Manga not found")
                chapters = await get_manga_chapters(session, manga_id, limit=2000)
                covers = await covers_for_group(session, manga.group_key)
                manga_out = _manga_out(manga, covers)
                return MangaDetailOut(
                    **manga_out.model_dump(),
                    chapters=[_chapter_out(chapter) for chapter in chapters],
                )

        return await retry_on_locked(read)

    async def recommendations(self, payload: RecommendationRequest) -> RecommendationResult:
        key = recommendation_cache_key(
            seed_manga_id=payload.seed_manga_id,
            history_ids=payload.history_ids,
            bookmark_ids=payload.bookmark_ids,
            exclude_ids=payload.exclude_ids,
            limit=payload.limit,
        )
        cached = recommendation_cache.get(key)
        if cached is not None:
            return cached

        async def read() -> RecommendationResult:
            async with self.session_factory() as session:
                rows, strategy = await recommend_manga(
                    session,
                    seed_manga_id=payload.seed_manga_id,
                    history_ids=payload.history_ids,
                    bookmark_ids=payload.bookmark_ids,
                    exclude_ids=payload.exclude_ids,
                    limit=payload.limit,
                )
                return RecommendationResult(
                    items=[_manga_out(row) for row in rows],
                    strategy=strategy,  # type: ignore[arg-type]
                )

        result = await retry_on_locked(read)
        recommendation_cache.set(key, result)
        return result

    async def _similar_out(
        self,
        session: AsyncSession,
        seed,  # type: ignore[no-untyped-def]
        *,
        history_ids: list[uuid.UUID] | None = None,
        exclude_ids: list[uuid.UUID] | None = None,
        limit: int = 12,
    ) -> list[MangaOut]:
        history = list(dict.fromkeys(history_ids or []))
        explicit = list(dict.fromkeys(exclude_ids or []))
        target = max(6, min(limit, 12))
        key = discovery_cache_key(
            "similar",
            seed.id,
            ",".join(str(item) for item in sorted(history)),
            ",".join(str(item) for item in sorted(explicit)),
            target,
        )
        cached = similar_cache.get(key)
        if cached is not None:
            return cached
        rows = await similar_manga(
            session,
            seed,
            history_ids=history,
            exclude_ids=explicit,
            limit=target,
        )
        result = [_manga_out(row) for row in rows]
        similar_cache.set(key, result)
        return result

    async def similar(
        self,
        manga_id: uuid.UUID,
        *,
        history_ids: list[uuid.UUID] | None = None,
        limit: int = 12,
    ) -> list[MangaOut]:
        async def read() -> list[MangaOut]:
            async with self.session_factory() as session:
                seed = await find_manga(session, manga_id)
                if seed is None:
                    raise NotFoundError("Manga not found")
                return await self._similar_out(
                    session,
                    seed,
                    history_ids=history_ids,
                    limit=limit,
                )

        return await retry_on_locked(read)

    async def related(
        self,
        manga_id: uuid.UUID,
        *,
        history_ids: list[uuid.UUID] | None = None,
        limit: int = 12,
    ) -> RelatedMangaOut:
        async def read() -> RelatedMangaOut:
            async with self.session_factory() as session:
                manga = await find_manga(session, manga_id)
                if manga is None:
                    raise NotFoundError("Manga not found")
                series, related = await manga_relations(session, manga_id)
                explicit_ids = [row.id for row in [*series, *related]]
                rows = await self._similar_out(
                    session,
                    manga,
                    history_ids=history_ids,
                    exclude_ids=explicit_ids,
                    limit=limit,
                )
                return RelatedMangaOut(
                    series=[_manga_out(row) for row in series],
                    related=[_manga_out(row) for row in related],
                    similar=rows,
                )

        return await retry_on_locked(read)

    async def collections(self, *, limit: int = 12) -> CollectionListOut:
        key = discovery_cache_key("collections", max(1, min(limit, 24)))
        cached = collection_cache.get(key)
        if cached is not None:
            return cached
        async with self.session_factory() as session:
            collections = await list_collections(session, enabled_only=True)
            items: list[CollectionOut] = []
            for collection in collections:
                preview = max(1, min(limit, collection.limit or limit))
                rows = await collection_manga(session, collection, limit=preview)
                if not rows:
                    continue
                items.append(_collection_out(collection, rows))
            result = CollectionListOut(items=items, total=len(items))
        collection_cache.set(key, result)
        return result

    async def collection(self, slug: str, *, limit: int = 24) -> CollectionOut:
        key = discovery_cache_key("collection", slug, max(1, min(limit, 60)))
        cached = collection_cache.get(key)
        if cached is not None:
            return cached
        async with self.session_factory() as session:
            collection = await find_collection_by_slug(session, slug)
            if collection is None or not collection.enabled:
                raise NotFoundError("Collection not found")
            rows = await collection_manga(session, collection, limit=limit)
            result = _collection_out(collection, rows)
        collection_cache.set(key, result)
        return result

    async def admin_collections(self) -> CollectionListOut:
        async with self.session_factory() as session:
            collections = await list_collections(session)
            items: list[CollectionOut] = []
            for collection in collections:
                rows = await collection_manga(session, collection, limit=60)
                items.append(_collection_out(collection, rows))
            return CollectionListOut(items=items, total=len(items))

    async def create_collection(self, payload: CollectionCreate) -> CollectionOut:
        async with self.session_factory() as session:
            collection = await create_collection(session, payload)
            await session.commit()
            clear_discovery_caches()
            rows = await collection_manga(session, collection, limit=60)
            return _collection_out(collection, rows)

    async def update_collection(
        self, collection_id: uuid.UUID, payload: CollectionUpdate
    ) -> CollectionOut:
        async with self.session_factory() as session:
            collection = await find_collection(session, collection_id)
            if collection is None:
                raise NotFoundError("Collection not found")
            await update_collection(session, collection, payload)
            await session.commit()
            clear_discovery_caches()
            rows = await collection_manga(session, collection, limit=60)
            return _collection_out(collection, rows)

    async def delete_collection(self, collection_id: uuid.UUID) -> None:
        async with self.session_factory() as session:
            collection = await find_collection(session, collection_id)
            if collection is None:
                raise NotFoundError("Collection not found")
            await delete_collection(session, collection)
            await session.commit()
            clear_discovery_caches()

    async def add_collection_item(
        self, collection_id: uuid.UUID, payload: CollectionItemIn
    ) -> CollectionOut:
        async with self.session_factory() as session:
            collection = await find_collection(session, collection_id)
            if collection is None:
                raise NotFoundError("Collection not found")
            await add_collection_item(session, collection, payload.manga_id)
            await session.commit()
            clear_discovery_caches()
            rows = await collection_manga(session, collection, limit=60)
            return _collection_out(collection, rows)

    async def remove_collection_item(
        self, collection_id: uuid.UUID, manga_id: uuid.UUID
    ) -> CollectionOut:
        async with self.session_factory() as session:
            collection = await find_collection(session, collection_id)
            if collection is None:
                raise NotFoundError("Collection not found")
            await remove_collection_item(session, collection, manga_id)
            await session.commit()
            clear_discovery_caches()
            rows = await collection_manga(session, collection, limit=60)
            return _collection_out(collection, rows)

    async def reorder_collection_items(
        self, collection_id: uuid.UUID, payload: CollectionOrderIn
    ) -> CollectionOut:
        async with self.session_factory() as session:
            collection = await find_collection(session, collection_id)
            if collection is None:
                raise NotFoundError("Collection not found")
            await reorder_collection_items(session, collection, payload.manga_ids)
            await session.commit()
            clear_discovery_caches()
            rows = await collection_manga(session, collection, limit=60)
            return _collection_out(collection, rows)

    async def collection_audit(self, *, limit: int = 100) -> list[CollectionAuditOut]:
        async with self.session_factory() as session:
            rows = await list_collection_audit(session, limit=limit)
            return [
                CollectionAuditOut(
                    id=row.id,
                    action=row.action,
                    collection_id=row.collection_id,
                    details=row.details or {},
                    created_at=row.created_at,
                )
                for row in rows
            ]

    async def link_relations(
        self, manga_id: uuid.UUID, payload: RelationsIn
    ) -> RelationsOut:
        async with self.session_factory() as session:
            manga = await find_manga(session, manga_id)
            if manga is None:
                raise NotFoundError("Manga not found")
            linked = 0
            for item in payload.items:
                if item.to_manga_id == manga_id:
                    raise NotFoundError("Нельзя связать тайтл с самим собой")
                target = await find_manga(session, item.to_manga_id)
                if target is None:
                    raise NotFoundError(f"Manga {item.to_manga_id} not found")
                await upsert_relation(
                    session,
                    from_manga_id=manga_id,
                    to_manga_id=item.to_manga_id,
                    relation=item.relation,
                    series_key=item.series_key,
                )
                linked += 1
            await session.commit()
            clear_discovery_caches()
            return RelationsOut(linked=linked)

    async def manga_by_source(self, source: str, source_id: str) -> MangaDetailOut:
        from .repository import find_manga_by_source

        async def read() -> MangaDetailOut:
            async with self.session_factory() as session:
                manga = await find_manga_by_source(session, source, source_id)
                if manga is None:
                    raise NotFoundError("Manga not found")
                chapters = await get_manga_chapters(session, manga.id, limit=2000)
                covers = await covers_for_group(session, manga.group_key)
                manga_out = _manga_out(manga, covers)
                return MangaDetailOut(
                    **manga_out.model_dump(),
                    chapters=[_chapter_out(chapter) for chapter in chapters],
                )

        return await retry_on_locked(read)

    async def list(
        self,
        *,
        query: str | None = None,
        source: str | None = None,
        genre: str | None = None,
        genres: list[str] | None = None,
        year: int | None = None,
        status: str | None = None,
        include_empty: bool = False,
        sort: str = "popular",
        page: int = 1,
        limit: int = 24,
    ) -> MangaListResponse:
        async def read() -> MangaListResponse:
            async with self.session_factory() as session:
                items, total = await list_manga(
                    session,
                    query=query,
                    source=source,
                    genre=genre,
                    genres=genres,
                    year=year,
                    status=status,
                    include_empty=include_empty,
                    sort=sort,
                    page=page,
                    limit=limit,
                )
                return MangaListResponse(
                    items=[_manga_out(item) for item in items],
                    total=total,
                    page=page,
                    limit=limit,
                    has_next=(page - 1) * limit + limit < total,
                )

        return await retry_on_locked(read)

    async def suggest(self, query: str, *, limit: int = 6) -> SuggestResponse:
        """Instant local suggestions; this method has no parser dependency."""

        async def read() -> SuggestResponse:
            async with self.session_factory() as session:
                rows = await suggest_manga(session, query, limit=limit)
                items = [
                    SearchSuggestionOut(
                        id=row.id,
                        title=row.title,
                        title_en=row.title_en,
                        poster_url=row.poster_url,
                        year=row.year,
                        source=row.source,
                        url_slug=row.url_slug or build_url_slug(row.title),
                        reason=suggestion_reason(reason),
                    )
                    for row, reason in rows
                ]
                return SuggestResponse(query=query, items=items, total=len(items))

        return await retry_on_locked(read)

    async def chapters(
        self, manga_id: uuid.UUID, *, query: str | None = None, page: int = 1, limit: int = 200
    ) -> list[ChapterOut]:
        async def read() -> list[ChapterOut]:
            async with self.session_factory() as session:
                manga = await find_manga(session, manga_id)
                if manga is None:
                    raise NotFoundError("Manga not found")
                chapters = await get_manga_chapters(
                    session,
                    manga_id,
                    limit=limit,
                    offset=(page - 1) * limit,
                    query=query,
                )
                return [_chapter_out(chapter) for chapter in chapters]

        return await retry_on_locked(read)

    async def chapter_detail(
        self, chapter_id: uuid.UUID, *, refresh: bool = True
    ) -> ChapterDetailInternal:
        async with self.session_factory() as session:
            chapter = await get_chapter(session, chapter_id)
            if chapter is None:
                raise NotFoundError("Chapter not found")
            cached_at = chapter.pages_cached_at
            if cached_at is not None and cached_at.tzinfo is None:
                cached_at = cached_at.replace(tzinfo=UTC)
            has_cached_pages = bool(chapter.pages)
            stale = (
                not has_cached_pages
                or cached_at is None
                or cached_at
                < datetime.now(UTC) - timedelta(minutes=self.settings.pages_stale_minutes)
            )
            if refresh and stale:
                try:
                    upstream = await self.parser.chapter(
                        chapter.source,
                        source_id=chapter.source_id,
                        url=chapter.url,
                    )
                    pages = [page.model_dump(mode="json") for page in upstream.pages]
                    if pages:
                        await update_chapter_pages(
                            session, chapter, pages, is_horizontal=upstream.is_horizontal
                        )
                        chapter.page_count = len(pages)
                    await session.commit()
                except (UpstreamError, NotFoundError) as exc:
                    await session.rollback()
                    logger.warning(
                        "chapter page refresh failed",
                        extra={"chapter_id": str(chapter_id), "error": str(exc)},
                    )
                    if not has_cached_pages:
                        raise UpstreamError(
                            "Chapter pages are temporarily unavailable",
                            details={"chapter_id": str(chapter_id)},
                        ) from exc
                    chapter = await get_chapter(session, chapter_id)
                    if chapter is None:
                        raise NotFoundError("Chapter not found") from exc

            chapter = await get_chapter(session, chapter_id)
            if chapter is None:
                raise NotFoundError("Chapter not found")
            ids = await ordered_chapter_ids(session, chapter.manga_id)
            index = ids.index(chapter.id) if chapter.id in ids else -1
            prev_id = ids[index - 1] if index > 0 else None
            next_id = ids[index + 1] if 0 <= index < len(ids) - 1 else None
            pages = [
                PageOut(
                    number=int(page.get("number") or idx + 1),
                    url=str(page.get("url")),
                    width=page.get("width"),
                    height=page.get("height"),
                )
                for idx, page in enumerate(chapter.pages or [])
            ]
            base = _chapter_out(chapter)
            return ChapterDetailInternal(
                **base.model_dump(),
                pages=[page.model_dump(mode="json") for page in pages],
                prev_chapter_id=prev_id,
                next_chapter_id=next_id,
                is_horizontal=chapter.is_horizontal,
            )

    async def refresh_stale(self, limit: int | None = None) -> RefreshResult:
        batch = limit or self.settings.refresh_batch_size
        async with self.session_factory() as session:
            stale = await stale_manga(
                session,
                older_than_minutes=self.settings.refresh_min_interval_minutes,
                limit=batch,
            )
            targets = [
                {
                    "id": manga.id,
                    "source": manga.source,
                    "source_id": manga.source_id,
                    "url": manga.url,
                    "title": manga.title,
                }
                for manga in stale
            ]

        refreshed = 0
        failed = 0
        events: list[NewChapterEvent] = []
        errors: list[str] = []
        for target in targets:
            try:
                detail = await self.parser.manga(
                    target["source"], source_id=target["source_id"], url=target["url"]
                )
                result = await self.import_detail(detail)
                refreshed += 1
                for chapter in result.new_chapters:
                    events.append(
                        NewChapterEvent(
                            manga_id=result.manga.id,
                            manga_title=result.manga.title,
                            chapter_id=chapter.id,
                            chapter_label=f"Том {chapter.volume}, глава {chapter.number}"
                            if chapter.volume
                            else f"Глава {chapter.number}",
                            source=target["source"],
                            url=chapter.url,
                            published_at=chapter.published_at,
                        )
                    )
            except Exception as exc:
                failed += 1
                errors.append(f"{target['title']}: {exc}")
                logger.warning(
                    "manga refresh failed",
                    extra={"manga_id": str(target["id"]), "error": str(exc)},
                )
        return RefreshResult(
            refreshed=refreshed, failed=failed, new_chapters=events, errors=errors
        )

    async def sync_sources(self, sources: list[SourceInfo]) -> int:
        async with self.session_factory() as session:
            for info in sources:
                await upsert_source(session, info)
            await session.commit()
        return len(sources)

    async def catalog_stats(self) -> CatalogStats:
        async def read() -> CatalogStats:
            async with self.session_factory() as session:
                return await stats(session)

        return await retry_on_locked(read)

    async def source_rows(self) -> list[Any]:
        async def read() -> list[Any]:
            async with self.session_factory() as session:
                return list(await list_sources(session))

        return await retry_on_locked(read)

    async def sitemap_entries(self, *, limit: int = 50_000) -> list[SitemapEntryOut]:
        async def read() -> list[SitemapEntryOut]:
            async with self.session_factory() as session:
                rows = await repo_sitemap_entries(session, limit=limit)
                return [
                    SitemapEntryOut(
                        id=row[0],
                        url_slug=row[1],
                        title=row[2] or "",
                        last_chapter_at=row[3],
                        updated_at=row[4],
                    )
                    for row in rows
                ]

        return await retry_on_locked(read)

    async def search_backfill(self) -> SearchBackfillStats | None:
        async def read() -> SearchBackfillStats | None:
            async with self.session_factory() as session:
                return await search_backfill_stats(session)

        return await retry_on_locked(read)

    async def genres(self) -> GenreListOut:
        async def read() -> GenreListOut:
            async with self.session_factory() as session:
                rows = await list_genres(session)
                items = [GenreOut(**row) for row in rows]
                return GenreListOut(items=items, total=len(items))

        return await retry_on_locked(read)

    async def home_updates(self, *, limit: int = 25) -> HomeUpdatesOut:
        async def read() -> HomeUpdatesOut:
            async with self.session_factory() as session:
                rows = await latest_updates(session, limit=limit)
                items = [
                    HomeUpdateOut(
                        manga_id=manga.id,
                        manga_title=manga.title,
                        poster_url=manga.poster_url,
                        source=chapter.source,
                        chapter_id=chapter.id,
                        chapter_number=chapter.number,
                        chapter_volume=chapter.volume,
                        chapter_title=chapter.title,
                        published_at=chapter.published_at,
                        added_at=chapter.created_at,
                    )
                    for chapter, manga in rows
                ]
                return HomeUpdatesOut(items=items, total=len(items))

        return await retry_on_locked(read)

    async def pending_enrichment(self, *, source: str, limit: int = 50) -> PendingEnrichmentListOut:
        async def read() -> PendingEnrichmentListOut:
            async with self.session_factory() as session:
                rows = await pending_enrichment(session, source=source, limit=limit)
                items = [
                    PendingEnrichmentOut(
                        manga_id=row.id,
                        source=row.source,
                        source_id=row.source_id,
                        title=row.title,
                        url=row.url,
                    )
                    for row in rows
                ]
                return PendingEnrichmentListOut(items=items, total=len(items))

        return await retry_on_locked(read)

    async def crawl_states(self, *, source: str | None = None) -> list[CrawlStateOut]:
        async def read() -> list[CrawlStateOut]:
            async with self.session_factory() as session:
                rows = await list_crawl_states(session, source=source)
                return [_crawl_state_out(row) for row in rows]

        return await retry_on_locked(read)

    async def crawl_state(self, source: str, mode: str = "full") -> CrawlStateOut | None:
        async def read() -> CrawlStateOut | None:
            async with self.session_factory() as session:
                row = await get_crawl_state(session, source, mode)
                return _crawl_state_out(row) if row is not None else None

        return await retry_on_locked(read)

    async def record_enrichment_failure(
        self, manga_id: uuid.UUID, payload: EnrichmentFailureRequest
    ) -> dict[str, Any]:
        async with self.session_factory() as session:
            manga = await record_enrichment_failure(
                session,
                manga_id,
                error=payload.error,
                permanent=payload.permanent,
                base_seconds=self.settings.enrichment_retry_base_seconds,
                max_seconds=self.settings.enrichment_retry_max_seconds,
            )
            if manga is None:
                raise NotFoundError("Manga not found")
            await session.commit()
            return {
                "manga_id": str(manga.id),
                "attempts": manga.enrichment_attempts,
                "retry_at": manga.enrichment_retry_at.isoformat()
                if manga.enrichment_retry_at
                else None,
            }

    async def enrichment_stats(
        self, *, rate_per_minute: int = 36, requests_per_title: int = 2
    ) -> EnrichmentStats:
        async def read() -> EnrichmentStats:
            async with self.session_factory() as session:
                payload = await enrichment_stats(
                    session,
                    rate_per_minute=rate_per_minute,
                    requests_per_title=requests_per_title,
                )
                return EnrichmentStats(**payload)

        return await retry_on_locked(read)

    async def rotate_enrichment(
        self, *, source: str | None = None, limit: int = 500
    ) -> int:
        async with self.session_factory() as session:
            count = await rotate_enrichment(session, source=source, limit=limit)
            await session.commit()
            return count

    async def reset_enrichment(
        self, *, source: str | None = None, limit: int = 500
    ) -> int:
        from .repository import reset_enrichment

        async with self.session_factory() as session:
            count = await reset_enrichment(session, source=source, limit=limit)
            await session.commit()
            return count

    async def save_crawl_state(self, payload: CrawlStateIn) -> CrawlStateOut:
        async with self.session_factory() as session:
            row = await upsert_crawl_state(session, payload.model_dump())
            await session.commit()
            return _crawl_state_out(row)

    async def chapter_label(self, chapter_id: uuid.UUID) -> str:
        async def read() -> str:
            async with self.session_factory() as session:
                chapter = await get_chapter(session, chapter_id)
                if chapter is None:
                    raise NotFoundError("Chapter not found")
                return chapter_label(chapter)

        return await retry_on_locked(read)
