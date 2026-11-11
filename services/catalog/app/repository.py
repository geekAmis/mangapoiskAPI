from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from manga_common.source_models import MangaDetail, MangaSummary, SourceInfo
from sqlalchemy import Integer, String, case, cast, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import Chapter, Manga, Source
from .schemas import CatalogStats, SourceStats


async def upsert_source(session: AsyncSession, info: SourceInfo) -> Source:
    source = await session.get(Source, info.code)
    capabilities = info.capabilities.model_dump()
    if source is None:
        source = Source(
            code=info.code,
            name=info.name,
            base_url=info.base_url,
            language=info.language,
            enabled=info.enabled,
            requires_cookies=info.requires_cookies,
            capabilities=capabilities,
        )
        session.add(source)
    else:
        source.name = info.name
        source.base_url = info.base_url
        source.language = info.language
        source.enabled = info.enabled
        source.requires_cookies = info.requires_cookies
        source.capabilities = capabilities
    return source


async def ensure_source(session: AsyncSession, code: str, name: str | None = None) -> Source:
    source = await session.get(Source, code)
    if source is None:
        source = Source(
            code=code,
            name=name or code,
            base_url="",
            enabled=True,
            capabilities={},
        )
        session.add(source)
        await session.flush()
    return source


async def find_manga(session: AsyncSession, manga_id: uuid.UUID) -> Manga | None:
    return await session.get(Manga, manga_id)


async def find_manga_by_source(
    session: AsyncSession, source: str, source_id: str
) -> Manga | None:
    return await session.scalar(
        select(Manga).where(Manga.source == source, Manga.source_id == source_id)
    )


def _clean(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


def _weak_title(value: str | None) -> bool:
    """Detect slug-derived titles such as ``gwihwanjaui mabeobeun ...``.

    MangaLib's detail endpoint is not public, so its fallback can produce a
    lowercase romanised slug.  A real Russian/English title from search should
    win over that placeholder.
    """

    text = (value or "").strip()
    if not text:
        return True
    if re.search(r"[А-Яа-яЁё]", text):
        return False
    if any(char.isupper() for char in text):
        return False
    return bool(re.fullmatch(r"[a-z0-9 .'’\-]+", text))


async def upsert_manga_detail(
    session: AsyncSession, detail: MangaDetail
) -> tuple[Manga, bool, list[Chapter]]:
    """Create/update a manga and its chapters.

    Returns ``(manga, created, new_chapters)``.  Page URLs are never touched
    here: chapters are refreshed separately when somebody opens them.
    """

    await ensure_source(session, detail.source)
    manga = await find_manga_by_source(session, detail.source, detail.source_id)
    created = manga is None
    if manga is None:
        manga = Manga(
            source=detail.source,
            source_id=detail.source_id,
            title=detail.title,
            slug=detail.slug,
        )
        session.add(manga)

    manga.slug = detail.slug or manga.slug
    if detail.title and (not _weak_title(detail.title) or _weak_title(manga.title)):
        manga.title = detail.title
    manga.title_en = detail.title_en or manga.title_en
    manga.title_alt = detail.title_alt or manga.title_alt
    manga.description = detail.description or manga.description
    manga.year = detail.year or manga.year
    manga.status = detail.status or manga.status
    manga.content_type = detail.content_type or manga.content_type
    manga.rating = detail.rating if detail.rating is not None else manga.rating
    manga.rating_count = (
        detail.rating_count if detail.rating_count is not None else manga.rating_count
    )
    manga.poster_url = detail.poster_url or manga.poster_url
    manga.adult = bool(detail.adult)
    manga.genres = list(detail.genres or [])
    manga.url = detail.url or manga.url
    manga.last_synced_at = datetime.now(UTC)
    await session.flush()

    new_chapters: list[Chapter] = []
    for summary in detail.chapters:
        if not summary.source_id:
            continue
        chapter = await session.scalar(
            select(Chapter).where(
                Chapter.manga_id == manga.id, Chapter.source_id == summary.source_id
            )
        )
        if chapter is None:
            chapter = Chapter(
                manga_id=manga.id,
                source=detail.source,
                source_id=summary.source_id,
                number=summary.number or "0",
                title=summary.title or "",
            )
            session.add(chapter)
            new_chapters.append(chapter)
        chapter.volume = summary.volume
        chapter.number = summary.number or chapter.number
        chapter.title = summary.title or chapter.title
        chapter.published_at = summary.published_at or chapter.published_at
        chapter.page_count = summary.page_count or chapter.page_count
        chapter.url = summary.url or chapter.url
        chapter.is_external = bool(summary.is_external)

    await session.flush()
    count, latest = (
        await session.execute(
            select(func.count(Chapter.id), func.max(Chapter.published_at)).where(
                Chapter.manga_id == manga.id
            )
        )
    ).one()
    manga.chapters_count = int(count or 0)
    manga.last_chapter_at = latest
    await session.flush()
    return manga, created, new_chapters


async def upsert_manga_summary(
    session: AsyncSession, summary: MangaSummary
) -> tuple[Manga, bool]:
    """Store a search result without touching chapters.

    Search results are cheap and useful immediately; the full chapter list is
    fetched lazily when a user opens the title.
    """

    await ensure_source(session, summary.source)
    manga = await find_manga_by_source(session, summary.source, summary.source_id)
    created = manga is None
    if manga is None:
        manga = Manga(
            source=summary.source,
            source_id=summary.source_id,
            title=summary.title,
            slug=summary.slug,
        )
        session.add(manga)
    manga.slug = summary.slug or manga.slug
    if summary.title and (not _weak_title(summary.title) or _weak_title(manga.title)):
        manga.title = summary.title
    manga.title_en = summary.title_en or manga.title_en
    manga.title_alt = summary.title_alt or manga.title_alt
    manga.description = summary.description or manga.description
    manga.year = summary.year or manga.year
    manga.status = summary.status or manga.status
    manga.content_type = summary.content_type or manga.content_type
    manga.rating = summary.rating if summary.rating is not None else manga.rating
    manga.rating_count = (
        summary.rating_count if summary.rating_count is not None else manga.rating_count
    )
    manga.poster_url = summary.poster_url or manga.poster_url
    manga.adult = bool(summary.adult)
    manga.genres = list(summary.genres or [])
    manga.url = summary.url or manga.url
    manga.last_synced_at = None if created else manga.last_synced_at
    await session.flush()
    return manga, created


async def get_manga_chapters(
    session: AsyncSession,
    manga_id: uuid.UUID,
    *,
    limit: int = 500,
    offset: int = 0,
    query: str | None = None,
) -> list[Chapter]:
    conditions = [Chapter.manga_id == manga_id]
    if query:
        pattern = f"%{query.strip()}%"
        conditions.append(
            or_(Chapter.title.ilike(pattern), Chapter.number.ilike(pattern), Chapter.volume.ilike(pattern))
        )
    volume_num = func.coalesce(cast(Chapter.volume, Integer), 0)
    number_num = func.coalesce(cast(Chapter.number, Integer), 0)
    result = await session.scalars(
        select(Chapter)
        .where(*conditions)
        .order_by(desc(volume_num), desc(number_num), desc(Chapter.created_at))
        .offset(offset)
        .limit(limit)
    )
    return list(result.all())


async def get_chapter(
    session: AsyncSession, chapter_id: uuid.UUID
) -> Chapter | None:
    return await session.scalar(
        select(Chapter).options(selectinload(Chapter.manga)).where(Chapter.id == chapter_id)
    )


async def get_chapter_by_manga_source(
    session: AsyncSession, manga_id: uuid.UUID, source_id: str
) -> Chapter | None:
    return await session.scalar(
        select(Chapter).where(Chapter.manga_id == manga_id, Chapter.source_id == source_id)
    )


async def ordered_chapter_ids(session: AsyncSession, manga_id: uuid.UUID) -> list[uuid.UUID]:
    volume_num = func.coalesce(cast(Chapter.volume, Integer), 0)
    number_num = func.coalesce(cast(Chapter.number, Integer), 0)
    result = await session.scalars(
        select(Chapter.id)
        .where(Chapter.manga_id == manga_id)
        .order_by(volume_num.asc(), number_num.asc(), Chapter.created_at.asc())
    )
    return list(result.all())


async def update_chapter_pages(
    session: AsyncSession,
    chapter: Chapter,
    pages: list[dict[str, Any]],
    *,
    is_horizontal: bool = False,
) -> Chapter:
    chapter.pages = pages
    chapter.page_count = len(pages)
    chapter.pages_cached_at = datetime.now(UTC)
    chapter.is_horizontal = is_horizontal
    await session.flush()
    return chapter


def _manga_conditions(
    *,
    query: str | None = None,
    source: str | None = None,
    genre: str | None = None,
    year: int | None = None,
    status: str | None = None,
) -> list[Any]:
    conditions: list[Any] = []
    if query:
        pattern = f"%{query.strip()}%"
        conditions.append(
            or_(
                Manga.title.ilike(pattern),
                Manga.title_en.ilike(pattern),
                Manga.title_alt.ilike(pattern),
                Manga.description.ilike(pattern),
            )
        )
    if source:
        conditions.append(Manga.source == source)
    if genre:
        conditions.append(func.lower(cast(Manga.genres, String)).like(f"%{genre.lower()}%"))
    if year:
        conditions.append(Manga.year == year)
    if status:
        conditions.append(Manga.status == status)
    return conditions


async def list_manga(
    session: AsyncSession,
    *,
    query: str | None = None,
    source: str | None = None,
    genre: str | None = None,
    year: int | None = None,
    status: str | None = None,
    sort: str = "popular",
    page: int = 1,
    limit: int = 24,
) -> tuple[list[Manga], int]:
    conditions = _manga_conditions(
        query=query, source=source, genre=genre, year=year, status=status
    )
    order_map = {
        "popular": (desc(Manga.rating_count), desc(Manga.rating), desc(Manga.updated_at)),
        "rating": (desc(Manga.rating), desc(Manga.rating_count)),
        "updated": (desc(Manga.last_chapter_at), desc(Manga.updated_at)),
        "title": (Manga.title.asc(),),
        "new": (desc(Manga.created_at),),
    }
    order_by = order_map.get(sort, order_map["popular"])
    total = int(
        (await session.scalar(select(func.count(Manga.id)).where(*conditions))) or 0
    )
    items = list(
        (
            await session.scalars(
                select(Manga)
                .where(*conditions)
                .order_by(*order_by)
                .offset((page - 1) * limit)
                .limit(limit)
            )
        ).all()
    )
    return items, total


async def stale_manga(
    session: AsyncSession, *, older_than_minutes: int, limit: int
) -> list[Manga]:
    cutoff = datetime.now(UTC) - timedelta(minutes=older_than_minutes)
    freshness = case((Manga.last_synced_at.is_(None), 0), else_=1)
    result = await session.scalars(
        select(Manga)
        .where(or_(Manga.last_synced_at.is_(None), Manga.last_synced_at < cutoff))
        .order_by(freshness, Manga.last_synced_at.asc(), Manga.updated_at.asc())
        .limit(limit)
    )
    return list(result.all())


async def list_sources(session: AsyncSession) -> list[Source]:
    result = await session.scalars(select(Source).order_by(Source.name.asc()))
    return list(result.all())


async def stats(session: AsyncSession) -> CatalogStats:
    manga_total = int((await session.scalar(select(func.count(Manga.id)))) or 0)
    chapter_total = int((await session.scalar(select(func.count(Chapter.id)))) or 0)
    rows = (
        await session.execute(
            select(
                Manga.source,
                func.count(Manga.id),
                func.coalesce(func.sum(Manga.chapters_count), 0),
            ).group_by(Manga.source)
        )
    ).all()
    sources = [
        SourceStats(source=row[0], manga=int(row[1]), chapters=int(row[2])) for row in rows
    ]
    return CatalogStats(manga=manga_total, chapters=chapter_total, sources=sources)


def manga_title(manga: Manga) -> str:
    return manga.title


def chapter_label(chapter: Chapter) -> str:
    parts = []
    if chapter.volume:
        parts.append(f"Том {chapter.volume}")
    parts.append(f"Глава {chapter.number}")
    if chapter.title:
        parts.append(chapter.title)
    return ", ".join(parts)


def summary_from_manga(manga: Manga) -> MangaSummary:
    return MangaSummary(
        source=manga.source,
        source_id=manga.source_id,
        slug=manga.slug,
        title=manga.title,
        title_en=manga.title_en,
        title_alt=manga.title_alt,
        description=manga.description,
        year=manga.year,
        status=manga.status,
        content_type=manga.content_type,
        rating=manga.rating,
        rating_count=manga.rating_count,
        poster_url=manga.poster_url,
        adult=manga.adult,
        genres=list(manga.genres or []),
        url=manga.url,
        updated_at=manga.updated_at,
    )
