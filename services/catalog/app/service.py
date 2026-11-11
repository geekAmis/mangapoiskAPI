from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from manga_common.errors import NotFoundError, UpstreamError
from manga_common.schemas import (
    ChapterOut,
    MangaDetailOut,
    MangaListResponse,
    MangaOut,
    PageOut,
)
from manga_common.source_models import MangaDetail, SourceInfo
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config import CatalogSettings
from .parser_client import ParserClient
from .repository import (
    chapter_label,
    find_manga,
    get_chapter,
    get_manga_chapters,
    list_manga,
    ordered_chapter_ids,
    stale_manga,
    stats,
    update_chapter_pages,
    upsert_manga_detail,
    upsert_source,
)
from .schemas import (
    CatalogStats,
    ChapterDetailInternal,
    ImportResult,
    NewChapterEvent,
    RefreshResult,
)

logger = logging.getLogger(__name__)


def _manga_out(manga) -> MangaOut:  # type: ignore[no-untyped-def]
    return MangaOut.model_validate(manga)


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
            chapters = await get_manga_chapters(session, manga.id, limit=2000)
            manga_out = _manga_out(manga)
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
            return _manga_out(manga)

    async def chapter_meta(self, chapter_id: uuid.UUID) -> ChapterOut:
        async with self.session_factory() as session:
            chapter = await get_chapter(session, chapter_id)
            if chapter is None:
                raise NotFoundError("Chapter not found")
            return _chapter_out(chapter)

    async def manga_detail(self, manga_id: uuid.UUID) -> MangaDetailOut:
        async with self.session_factory() as session:
            manga = await find_manga(session, manga_id)
            if manga is None:
                raise NotFoundError("Manga not found")
            chapters = await get_manga_chapters(session, manga_id, limit=2000)
            manga_out = _manga_out(manga)
            return MangaDetailOut(
                **manga_out.model_dump(),
                chapters=[_chapter_out(chapter) for chapter in chapters],
            )

    async def manga_by_source(self, source: str, source_id: str) -> MangaDetailOut:
        from .repository import find_manga_by_source

        async with self.session_factory() as session:
            manga = await find_manga_by_source(session, source, source_id)
            if manga is None:
                raise NotFoundError("Manga not found")
            chapters = await get_manga_chapters(session, manga.id, limit=2000)
            manga_out = _manga_out(manga)
            return MangaDetailOut(
                **manga_out.model_dump(),
                chapters=[_chapter_out(chapter) for chapter in chapters],
            )

    async def list(
        self,
        *,
        query: str | None = None,
        source: str | None = None,
        genre: str | None = None,
        year: int | None = None,
        status: str | None = None,
        sort: str = "popular",
        page: int = 1,
        limit: int = 24,
    ) -> MangaListResponse:
        async with self.session_factory() as session:
            items, total = await list_manga(
                session,
                query=query,
                source=source,
                genre=genre,
                year=year,
                status=status,
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

    async def chapters(
        self, manga_id: uuid.UUID, *, query: str | None = None, page: int = 1, limit: int = 200
    ) -> list[ChapterOut]:
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
        async with self.session_factory() as session:
            return await stats(session)

    async def chapter_label(self, chapter_id: uuid.UUID) -> str:
        async with self.session_factory() as session:
            chapter = await get_chapter(session, chapter_id)
            if chapter is None:
                raise NotFoundError("Chapter not found")
            return chapter_label(chapter)
