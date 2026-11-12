from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from manga_common.db import retry_on_locked
from manga_common.errors import ForbiddenError, NotFoundError, UpstreamError
from manga_common.schemas import (
    ChapterOut,
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
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config import CatalogSettings
from .normalization import GENRE_LABELS, genre_slugs
from .parser_client import ParserClient
from .recommendations import recommendation_cache, recommendation_cache_key
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


def _chapter_out(chapter, manga=None) -> ChapterOut:  # type: ignore[no-untyped-def]
    payload = ChapterOut.model_validate(chapter)
    if manga is not None:
        payload.adult_only = bool(manga.adult_only)
        payload.requires_age_confirmation = bool(manga.requires_age_confirmation)
    return payload


def _ensure_adult_access(manga, *, adult_allowed: bool) -> None:  # type: ignore[no-untyped-def]
    """Refuse age-gated titles without leaking any of their content."""

    if adult_allowed:
        return
    if bool(manga.adult_only or manga.requires_age_confirmation):
        raise ForbiddenError(
            "Для просмотра этого тайтла нужно подтвердить возраст 18+",
            code="age_confirmation_required",
            details={
                "manga_id": str(manga.id),
                "age_confirmation_required": True,
            },
        )


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
        self,
        source: str,
        *,
        source_id: str | None = None,
        url: str | None = None,
        adult_allowed: bool = False,
    ) -> ImportResult:
        from .repository import ensure_source

        async with self.session_factory() as session:
            source_row = await ensure_source(session, source)
            if (source_row.adult_only or source_row.requires_age_confirmation) and not adult_allowed:
                raise ForbiddenError(
                    "Для просмотра этого источника нужно подтвердить возраст 18+",
                    code="age_confirmation_required",
                    details={"source": source, "age_confirmation_required": True},
                )
            await session.commit()
        if not adult_allowed:
            # A source row may not have been synchronised yet (first deploy or
            # a manual import).  Ask the parser registry for the authoritative
            # adult flags before calling the upstream.
            try:
                infos = await self.parser.sources()
            except Exception:
                infos = []
            selected = next((item for item in infos if item.code == source), None)
            if selected is not None and (
                selected.adult_only or selected.requires_age_confirmation
            ):
                raise ForbiddenError(
                    "Для просмотра этого источника нужно подтвердить возраст 18+",
                    code="age_confirmation_required",
                    details={"source": source, "age_confirmation_required": True},
                )
        detail = await self.parser.manga(source, source_id=source_id, url=url)
        return await self.import_detail(detail)

    async def import_detail(self, detail: MangaDetail) -> ImportResult:
        async with self.session_factory() as session:
            manga, created, new_chapters = await upsert_manga_detail(session, detail)
            await session.commit()
            chapters = await get_manga_chapters(session, manga.id, limit=2000)
            covers = await covers_for_group(session, manga.group_key)
            manga_out = _manga_out(manga, covers)
            detail_out = MangaDetailOut(
                **manga_out.model_dump(),
                chapters=[_chapter_out(chapter, manga) for chapter in chapters],
            )
            return ImportResult(
                manga=detail_out,
                source=detail.source,
                created=created,
                imported_chapters=len(new_chapters),
                imported_pages=sum(chapter.page_count for chapter in new_chapters),
                new_chapters=[_chapter_out(chapter, manga) for chapter in new_chapters],
            )

    async def import_summary(self, summary) -> MangaOut:  # type: ignore[no-untyped-def]
        from .repository import upsert_manga_summary

        async with self.session_factory() as session:
            manga, _ = await upsert_manga_summary(session, summary)
            await session.commit()
            covers = await covers_for_group(session, manga.group_key)
            return _manga_out(manga, covers)

    async def chapter_meta(
        self, chapter_id: uuid.UUID, *, adult_allowed: bool = False
    ) -> ChapterOut:
        async with self.session_factory() as session:
            chapter = await get_chapter(session, chapter_id)
            if chapter is None:
                raise NotFoundError("Chapter not found")
            manga = await find_manga(session, chapter.manga_id)
            if manga is None:
                raise NotFoundError("Manga not found")
            _ensure_adult_access(manga, adult_allowed=adult_allowed)
            return _chapter_out(chapter, manga)

    async def variants(
        self, manga_id: uuid.UUID, *, adult_allowed: bool = False
    ) -> MangaVariantsOut:
        from .repository import manga_variants

        async with self.session_factory() as session:
            manga = await find_manga(session, manga_id)
            if manga is None:
                raise NotFoundError("Manga not found")
            _ensure_adult_access(manga, adult_allowed=adult_allowed)
            rows = await manga_variants(session, manga, adult_allowed=adult_allowed)
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

    async def manga_detail(
        self, manga_id: uuid.UUID, *, adult_allowed: bool = False
    ) -> MangaDetailOut:
        async with self.session_factory() as session:
            manga = await find_manga(session, manga_id)
            if manga is None:
                raise NotFoundError("Manga not found")
            _ensure_adult_access(manga, adult_allowed=adult_allowed)
            chapters = await get_manga_chapters(session, manga_id, limit=2000)
            covers = await covers_for_group(session, manga.group_key)
            manga_out = _manga_out(manga, covers)
            return MangaDetailOut(
                **manga_out.model_dump(),
                chapters=[_chapter_out(chapter, manga) for chapter in chapters],
            )

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
        async with self.session_factory() as session:
            rows, strategy = await recommend_manga(
                session,
                seed_manga_id=payload.seed_manga_id,
                history_ids=payload.history_ids,
                bookmark_ids=payload.bookmark_ids,
                exclude_ids=payload.exclude_ids,
                limit=payload.limit,
            )
            result = RecommendationResult(
                items=[_manga_out(row) for row in rows],
                strategy=strategy,  # type: ignore[arg-type]
            )
        recommendation_cache.set(key, result)
        return result

    async def related(
        self, manga_id: uuid.UUID, *, adult_allowed: bool = False
    ) -> RelatedMangaOut:
        async with self.session_factory() as session:
            manga = await find_manga(session, manga_id)
            if manga is None:
                raise NotFoundError("Manga not found")
            _ensure_adult_access(manga, adult_allowed=adult_allowed)
            series, related = await manga_relations(
                session, manga_id, adult_allowed=adult_allowed
            )
            return RelatedMangaOut(
                series=[_manga_out(row) for row in series],
                related=[_manga_out(row) for row in related],
            )

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
            return RelationsOut(linked=linked)

    async def manga_by_source(
        self, source: str, source_id: str, *, adult_allowed: bool = False
    ) -> MangaDetailOut:
        from .repository import find_manga_by_source

        async with self.session_factory() as session:
            manga = await find_manga_by_source(session, source, source_id)
            if manga is None:
                raise NotFoundError("Manga not found")
            _ensure_adult_access(manga, adult_allowed=adult_allowed)
            chapters = await get_manga_chapters(session, manga.id, limit=2000)
            covers = await covers_for_group(session, manga.group_key)
            manga_out = _manga_out(manga, covers)
            return MangaDetailOut(
                **manga_out.model_dump(),
                chapters=[_chapter_out(chapter, manga) for chapter in chapters],
            )

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
        adult_allowed: bool = False,
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
                    adult_allowed=adult_allowed,
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

    async def suggest(
        self, query: str, *, limit: int = 6, adult_allowed: bool = False
    ) -> SuggestResponse:
        """Instant local suggestions; this method has no parser dependency."""

        async def read() -> SuggestResponse:
            async with self.session_factory() as session:
                rows = await suggest_manga(
                    session, query, limit=limit, adult_allowed=adult_allowed
                )
                items = [
                    SearchSuggestionOut(
                        id=row.id,
                        title=row.title,
                        title_en=row.title_en,
                        poster_url=row.poster_url,
                        year=row.year,
                        source=row.source,
                        reason=suggestion_reason(reason),
                    )
                    for row, reason in rows
                ]
                return SuggestResponse(query=query, items=items, total=len(items))

        return await retry_on_locked(read)

    async def chapters(
        self,
        manga_id: uuid.UUID,
        *,
        query: str | None = None,
        page: int = 1,
        limit: int = 200,
        adult_allowed: bool = False,
    ) -> list[ChapterOut]:
        async with self.session_factory() as session:
            manga = await find_manga(session, manga_id)
            if manga is None:
                raise NotFoundError("Manga not found")
            _ensure_adult_access(manga, adult_allowed=adult_allowed)
            chapters = await get_manga_chapters(
                session,
                manga_id,
                limit=limit,
                offset=(page - 1) * limit,
                query=query,
            )
            return [_chapter_out(chapter, manga) for chapter in chapters]

    async def chapter_detail(
        self,
        chapter_id: uuid.UUID,
        *,
        refresh: bool = True,
        adult_allowed: bool = False,
    ) -> ChapterDetailInternal:
        async with self.session_factory() as session:
            chapter = await get_chapter(session, chapter_id)
            if chapter is None:
                raise NotFoundError("Chapter not found")
            manga = await find_manga(session, chapter.manga_id)
            if manga is None:
                raise NotFoundError("Manga not found")
            _ensure_adult_access(manga, adult_allowed=adult_allowed)
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
            base = _chapter_out(chapter, manga)
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

    async def source_rows(self, *, adult_allowed: bool = False) -> list[Any]:
        async def read() -> list[Any]:
            async with self.session_factory() as session:
                rows = list(await list_sources(session))
                if not adult_allowed:
                    rows = [
                        row
                        for row in rows
                        if not (row.adult_only or row.requires_age_confirmation)
                    ]
                return rows

        return await retry_on_locked(read)

    async def sitemap_entries(self, *, limit: int = 50_000) -> list[SitemapEntryOut]:
        async def read() -> list[SitemapEntryOut]:
            async with self.session_factory() as session:
                rows = await repo_sitemap_entries(session, limit=limit)
                return [
                    SitemapEntryOut(
                        id=row[0],
                        last_chapter_at=row[1],
                        updated_at=row[2],
                    )
                    for row in rows
                ]

        return await retry_on_locked(read)

    async def search_backfill(self) -> SearchBackfillStats | None:
        async with self.session_factory() as session:
            return await search_backfill_stats(session)

    async def genres(self) -> GenreListOut:
        async with self.session_factory() as session:
            rows = await list_genres(session)
            items = [GenreOut(**row) for row in rows]
            return GenreListOut(items=items, total=len(items))

    async def home_updates(self, *, limit: int = 25) -> HomeUpdatesOut:
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

    async def pending_enrichment(self, *, source: str, limit: int = 50) -> PendingEnrichmentListOut:
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

    async def crawl_states(self, *, source: str | None = None) -> list[CrawlStateOut]:
        async with self.session_factory() as session:
            rows = await list_crawl_states(session, source=source)
            return [_crawl_state_out(row) for row in rows]

    async def crawl_state(self, source: str, mode: str = "full") -> CrawlStateOut | None:
        async with self.session_factory() as session:
            row = await get_crawl_state(session, source, mode)
            return _crawl_state_out(row) if row is not None else None

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
        async with self.session_factory() as session:
            payload = await enrichment_stats(
                session,
                rate_per_minute=rate_per_minute,
                requests_per_title=requests_per_title,
            )
            return EnrichmentStats(**payload)

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
        async with self.session_factory() as session:
            chapter = await get_chapter(session, chapter_id)
            if chapter is None:
                raise NotFoundError("Chapter not found")
            return chapter_label(chapter)
