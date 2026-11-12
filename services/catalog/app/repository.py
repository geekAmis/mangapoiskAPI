from __future__ import annotations

import math
import re
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from manga_common.source_models import MangaDetail, MangaSummary, SourceInfo
from sqlalchemy import Integer, String, and_, case, cast, desc, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import Chapter, CrawlState, Manga, MangaCover, MangaRelation, Source
from .normalization import (
    GENRE_LABELS,
    canonical_genre,
    genre_slugs,
    normalize_text,
    parse_genre_filter,
    status_key,
)
from .schemas import CatalogStats, EnrichmentSourceStats, SourceStats

DESCRIPTION_FALLBACK = "Упс. Описание не нашлось в источниках"
ENRICHMENT_FAILED_ATTEMPTS = 5
ENRICHMENT_STALE_HOURS = 24


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


def compute_group_key(title: str | None) -> str:
    from manga_common.text import slugify

    text = title or ""
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(
        r"\b(перезапуск|reborn|reboot|new|новый|новая|продолжение|second season)\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"[^\w\s-]", " ", text, flags=re.UNICODE)
    return slugify(re.sub(r"\s+", " ", text).strip())[:180]


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


def cover_quality(url: str | None) -> float:
    """Rank cover resolutions without downloading the image."""

    lowered = (url or "").casefold()
    if not lowered:
        return 0.0
    if "_micro" in lowered or "thumbnail" in lowered or "/thumb/" in lowered:
        return 0.3
    if "_mini" in lowered or lowered.endswith("_thumb.jpg"):
        return 0.6
    return 1.0


def _cover_order():  # type: ignore[no-untyped-def]
    """Portable ordering: rating, quality, chapter count, then freshness."""

    return (
        case((MangaCover.rating.is_(None), 1), else_=0),
        desc(MangaCover.rating),
        case((MangaCover.quality.is_(None), 1), else_=0),
        desc(MangaCover.quality),
        desc(MangaCover.chapters_count),
        case((MangaCover.source_updated_at.is_(None), 1), else_=0),
        desc(MangaCover.source_updated_at),
        desc(MangaCover.updated_at),
    )


async def upsert_cover(
    session: AsyncSession,
    manga: Manga,
    url: str | None,
) -> MangaCover | None:
    """Create or refresh the cover contributed by this source variant."""

    if not (url or "").strip():
        return None
    cover = await session.scalar(
        select(MangaCover).where(
            MangaCover.manga_id == manga.id,
            MangaCover.source == manga.source,
        )
    )
    if cover is None:
        cover = MangaCover(
            manga_id=manga.id,
            source=manga.source,
            source_id=manga.source_id,
            url=url,
        )
        session.add(cover)
    cover.group_key = manga.group_key
    cover.source_id = manga.source_id
    cover.url = url
    cover.rating = manga.rating
    cover.quality = cover_quality(url)
    cover.chapters_count = int(manga.chapters_count or 0)
    cover.source_updated_at = manga.last_chapter_at
    await session.flush()
    return cover


async def refresh_group_primary_cover(session: AsyncSession, group_key: str | None) -> MangaCover | None:
    """Mark the best cover of a title group as primary.

    Priority is source rating, cover quality, chapter count and then freshness.
    Every source variant in the group shares the primary poster so a card never
    regresses to a lower-quality image just because a user opened another
    variant.
    """

    if not group_key:
        return None
    covers = list(
        (
            await session.scalars(
                select(MangaCover)
                .where(MangaCover.group_key == group_key)
                .order_by(*_cover_order())
            )
        ).all()
    )
    if not covers:
        return None
    primary = covers[0]
    for cover in covers:
        cover.is_primary = cover.id == primary.id
    variants = list(
        (await session.scalars(select(Manga).where(Manga.group_key == group_key))).all()
    )
    for variant in variants:
        if primary.url:
            variant.poster_url = primary.url
    await session.flush()
    return primary


async def merge_group_metadata(session: AsyncSession, group_key: str | None) -> None:
    """Merge description/genres across all source variants of a title.

    Empty values never overwrite non-empty values.  A description found in any
    variant becomes the group description, and genre labels are unioned so a
    genre filter keeps working no matter which variant matched first.
    """

    if not group_key:
        return
    variants = list(
        (await session.scalars(select(Manga).where(Manga.group_key == group_key))).all()
    )
    if not variants:
        return

    descriptions = [variant.description.strip() for variant in variants if variant.description]
    best_description = max(descriptions, key=len) if descriptions else None

    genre_order: list[str] = []
    seen: set[str] = set()
    for variant in variants:
        for label in variant.genres or []:
            key = normalize_text(label)
            if not key or key in seen:
                continue
            seen.add(key)
            genre_order.append(label)

    best_year = next((variant.year for variant in variants if variant.year), None)
    best_content_type = next(
        (variant.content_type for variant in variants if variant.content_type), None
    )
    best_status = next((variant.status for variant in variants if variant.status), None)
    best_title_en = next((variant.title_en for variant in variants if variant.title_en), None)
    best_title_alt = next((variant.title_alt for variant in variants if variant.title_alt), None)

    for variant in variants:
        if best_description and not (variant.description or "").strip():
            variant.description = best_description
        if genre_order:
            variant.genres = list(genre_order)
        variant.year = variant.year or best_year
        variant.content_type = variant.content_type or best_content_type
        variant.status = variant.status or best_status
        variant.title_en = variant.title_en or best_title_en
        variant.title_alt = variant.title_alt or best_title_alt
    await session.flush()


async def covers_for_group(session: AsyncSession, group_key: str | None) -> list[MangaCover]:
    if not group_key:
        return []
    return list(
        (
            await session.scalars(
                select(MangaCover)
                .where(MangaCover.group_key == group_key)
                .order_by(desc(MangaCover.is_primary), *_cover_order())
            )
        ).all()
    )


def genre_payload(manga: Manga) -> list[dict[str, object]]:
    """Canonical slug/label pairs for one catalogue row."""

    result: list[dict[str, object]] = []
    for slug in genre_slugs(manga.genres or []):
        result.append(
            {
                "slug": slug,
                "label": GENRE_LABELS.get(slug, slug),
            }
        )
    return result


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
    if detail.genres:
        manga.genres = list(detail.genres)
    manga.url = detail.url or manga.url
    manga.group_key = compute_group_key(manga.title)
    manga.last_synced_at = datetime.now(UTC)
    manga.enrichment_attempts = 0
    manga.enrichment_retry_at = None
    manga.enrichment_last_error = None
    manga.enrichment_last_attempt_at = manga.last_synced_at
    if detail.chapters_count is not None:
        manga.chapters_count = max(int(manga.chapters_count or 0), int(detail.chapters_count))
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
        chapter.translator = summary.translator or chapter.translator
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
    manga.chapters_count = max(int(count or 0), int(detail.chapters_count or 0))
    manga.last_chapter_at = latest
    await session.flush()

    await upsert_cover(session, manga, detail.poster_url or manga.poster_url)
    await merge_group_metadata(session, manga.group_key)
    await refresh_group_primary_cover(session, manga.group_key)
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
    if summary.genres:
        manga.genres = list(summary.genres)
    manga.url = summary.url or manga.url
    manga.group_key = compute_group_key(manga.title)
    if summary.chapters_count:
        manga.chapters_count = max(int(manga.chapters_count or 0), int(summary.chapters_count))
    manga.last_synced_at = None if created else manga.last_synced_at
    await session.flush()

    await upsert_cover(session, manga, summary.poster_url or manga.poster_url)
    await merge_group_metadata(session, manga.group_key)
    await refresh_group_primary_cover(session, manga.group_key)
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
    genres: list[str] | None = None,
    year: int | None = None,
    status: str | None = None,
    include_empty: bool = False,
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
    requested = (
        parse_genre_filter(genres) if isinstance(genres, str) else list(genres or [])
    )
    if genre:
        requested.append(genre)
    for raw in requested:
        key = canonical_genre(raw)
        if key:
            # AND semantics: every requested genre must be present.
            conditions.append(Manga.genres_key.contains(f"|{key}|", autoescape=True))
    if year:
        conditions.append(Manga.year == year)
    if status:
        key = status_key(status)
        if key:
            conditions.append(Manga.status_key == key)
    if not include_empty:
        # Production QA: never lead users to a card that has no chapters yet.
        # Both checks matter: a summary may know chapters_count before the
        # chapter rows are imported, and rows can exist while the counter is
        # stale after a partial migration.
        conditions.append(Manga.chapters_count > 0)
        conditions.append(exists(select(Chapter.id).where(Chapter.manga_id == Manga.id)))
    return conditions


async def list_manga(
    session: AsyncSession,
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
) -> tuple[list[Manga], int]:
    conditions = _manga_conditions(
        query=query,
        source=source,
        genre=genre,
        genres=genres,
        year=year,
        status=status,
        include_empty=include_empty,
    )
    order_map = {
        "popular": (desc(Manga.rating_count), desc(Manga.rating), desc(Manga.updated_at)),
        "rating": (desc(Manga.rating), desc(Manga.rating_count)),
        "updated": (desc(Manga.last_chapter_at), desc(Manga.updated_at)),
        "title": (Manga.title.asc(),),
        "new": (desc(Manga.created_at),),
    }
    order_by = order_map.get(sort, order_map["popular"])

    # One card per normalised title group.  The representative is the variant
    # with the most chapters, then the best rating, then the freshest row.
    group_expr = func.coalesce(func.nullif(Manga.group_key, ""), cast(Manga.id, String))
    total = int(
        (
            await session.scalar(
                select(func.count())
                .select_from(select(group_expr).where(*conditions).group_by(group_expr).subquery())
            )
        )
        or 0
    )
    ranked = (
        select(
            Manga.id.label("manga_id"),
            func.row_number()
            .over(
                partition_by=group_expr,
                order_by=(
                    desc(Manga.chapters_count),
                    case((Manga.rating.is_(None), 1), else_=0),
                    desc(Manga.rating),
                    desc(Manga.updated_at),
                ),
            )
            .label("row_number"),
        )
        .where(*conditions)
        .subquery()
    )
    items = list(
        (
            await session.scalars(
                select(Manga)
                .join(ranked, Manga.id == ranked.c.manga_id)
                .where(ranked.c.row_number == 1)
                .order_by(*order_by)
                .offset((page - 1) * limit)
                .limit(limit)
            )
        ).all()
    )
    return items, total


async def backfill_group_keys(session: AsyncSession) -> int:
    rows = list(
        (
            await session.scalars(
                select(Manga).where((Manga.group_key.is_(None)) | (Manga.group_key == ""))
            )
        ).all()
    )
    for manga in rows:
        manga.group_key = compute_group_key(manga.title)
    await session.flush()
    return len(rows)


async def manga_variants(session: AsyncSession, manga: Manga) -> list[dict[str, Any]]:
    if not manga.group_key:
        manga.group_key = compute_group_key(manga.title)
        await session.flush()
    rows = list(
        (
            await session.scalars(
                select(Manga)
                .where(Manga.group_key == manga.group_key)
                .order_by(desc(Manga.chapters_count), Manga.title.asc())
            )
        ).all()
    )
    if manga not in rows:
        rows.insert(0, manga)
    result: list[dict[str, Any]] = []
    for row in rows:
        translator_rows = (
            await session.execute(
                select(Chapter.translator, func.count(Chapter.id))
                .where(Chapter.manga_id == row.id)
                .group_by(Chapter.translator)
                .order_by(desc(func.count(Chapter.id)))
            )
        ).all()
        result.append(
            {
                "id": row.id,
                "title": row.title,
                "source": row.source,
                "source_id": row.source_id,
                "poster_url": row.poster_url,
                "rating": row.rating,
                "chapters_count": row.chapters_count,
                "translators": [
                    {"name": name or "Без перевода", "count": int(count)}
                    for name, count in translator_rows
                ],
            }
        )
    return result


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


def _enrichment_pending_condition(now: datetime | None = None) -> Any:
    """Titles that still need a detail import.

    A title is pending when it was never enriched, or when it still has no
    chapter rows and its last successful sync is older than the stale window.
    ``enrichment_retry_at`` is deliberately not part of this predicate so the
    same condition can be used for pending/retry counters.
    """

    current = now or datetime.now(UTC)
    return or_(
        Manga.last_synced_at.is_(None),
        and_(
            ~exists(select(Chapter.id).where(Chapter.manga_id == Manga.id)),
            or_(
                Manga.last_synced_at.is_(None),
                Manga.last_synced_at < current - timedelta(hours=ENRICHMENT_STALE_HOURS),
            ),
        ),
    )


def _enrichment_available_condition(now: datetime | None = None) -> Any:
    current = now or datetime.now(UTC)
    return and_(
        _enrichment_pending_condition(current),
        or_(Manga.enrichment_retry_at.is_(None), Manga.enrichment_retry_at <= current),
    )


async def pending_enrichment(
    session: AsyncSession, *, source: str | None = None, limit: int = 50
) -> list[Manga]:
    """Titles discovered by the crawler but not yet hydrated with detail.

    Ordering is popularity-first, then oldest discovery.  Titles with a future
    ``enrichment_retry_at`` are skipped so a block of permanently failing
    titles cannot starve the rest of the queue (the pre-fix behaviour).
    """

    now = datetime.now(UTC)
    conditions: list[Any] = [_enrichment_available_condition(now)]
    if source:
        conditions.append(Manga.source == source)
    result = await session.scalars(
        select(Manga)
        .where(*conditions)
        .order_by(
            case((Manga.rating_count.is_(None), 1), else_=0),
            desc(Manga.rating_count),
            case((Manga.rating.is_(None), 1), else_=0),
            desc(Manga.rating),
            Manga.created_at.asc(),
        )
        .limit(limit)
    )
    return list(result.all())


async def record_enrichment_failure(
    session: AsyncSession,
    manga_id: uuid.UUID,
    *,
    error: str,
    permanent: bool = False,
    base_seconds: int = 300,
    max_seconds: int = 21600,
) -> Manga | None:
    """Persist an exponential retry clock for one title."""

    manga = await session.get(Manga, manga_id)
    if manga is None:
        return None
    attempts = int(manga.enrichment_attempts or 0) + 1
    now = datetime.now(UTC)
    if permanent:
        delay = max(1, max_seconds)
    else:
        delay = min(
            max(1, base_seconds) * (2 ** min(max(0, attempts - 1), 12)),
            max(1, max_seconds),
        )
    manga.enrichment_attempts = attempts
    manga.enrichment_last_attempt_at = now
    manga.enrichment_retry_at = now + timedelta(seconds=delay)
    manga.enrichment_last_error = (error or "")[:4000]
    await session.flush()
    return manga


async def rotate_enrichment(
    session: AsyncSession, *, source: str | None = None, limit: int = 500
) -> int:
    """Queue a bounded rotation of already-enriched titles for refresh."""

    conditions = [Manga.last_synced_at.is_not(None)]
    if source:
        conditions.append(Manga.source == source)
    ids = list(
        (
            await session.scalars(
                select(Manga.id)
                .where(*conditions)
                .order_by(Manga.last_synced_at.asc())
                .limit(max(1, limit))
            )
        ).all()
    )
    if not ids:
        return 0
    await session.execute(
        update(Manga).where(Manga.id.in_(ids)).values(last_synced_at=None)
    )
    await session.flush()
    return len(ids)


async def reset_enrichment(
    session: AsyncSession, *, source: str | None = None, limit: int = 500
) -> int:
    """Backward-compatible bounded alias for :func:`rotate_enrichment`."""

    return await rotate_enrichment(session, source=source, limit=limit)


async def latest_updates(
    session: AsyncSession, *, limit: int = 25
) -> list[tuple[Chapter, Manga]]:
    """Latest chapters across every title, newest publication/import first."""

    order_at = func.coalesce(Chapter.published_at, Chapter.created_at)
    rows = (
        await session.execute(
            select(Chapter, Manga)
            .join(Manga, Chapter.manga_id == Manga.id)
            .where(Manga.chapters_count > 0)
            .order_by(desc(order_at), desc(Chapter.created_at))
            .limit(limit)
        )
    ).all()
    return [(row[0], row[1]) for row in rows]


async def list_genres(session: AsyncSession) -> list[dict[str, Any]]:
    """Canonical genre slugs with counts computed from stored filter keys."""

    rows = (
        await session.execute(
            select(Manga.id, Manga.group_key, Manga.genres_key).where(
                Manga.chapters_count > 0,
                exists(select(Chapter.id).where(Chapter.manga_id == Manga.id)),
            )
        )
    ).all()
    counts: dict[str, int] = {}
    seen_groups: set[str] = set()
    for manga_id, group_key, key in rows:
        group = group_key or str(manga_id)
        if group in seen_groups:
            continue
        seen_groups.add(group)
        if not key:
            continue
        for slug in str(key).strip("|").split("|"):
            if slug:
                counts[slug] = counts.get(slug, 0) + 1
    result = [
        {
            "slug": slug,
            "label": GENRE_LABELS.get(slug, slug),
            "count": count,
            "aliases": [],
        }
        for slug, count in counts.items()
    ]
    result.sort(key=lambda item: (-int(item["count"]), str(item["label"]).casefold()))
    return result


async def get_crawl_state(
    session: AsyncSession, source: str, mode: str = "full"
) -> CrawlState | None:
    return await session.scalar(
        select(CrawlState).where(CrawlState.source == source, CrawlState.mode == mode)
    )


async def list_crawl_states(
    session: AsyncSession, *, source: str | None = None
) -> list[CrawlState]:
    conditions = []
    if source:
        conditions.append(CrawlState.source == source)
    result = await session.scalars(select(CrawlState).where(*conditions).order_by(CrawlState.source))
    return list(result.all())


async def upsert_crawl_state(session: AsyncSession, values: dict[str, Any]) -> CrawlState:
    source = str(values["source"])
    mode = str(values.get("mode") or "full")
    state = await get_crawl_state(session, source, mode)
    if state is None:
        state = CrawlState(source=source, mode=mode)
        session.add(state)
    for field in (
        "page",
        "status",
        "last_error",
        "next_run_at",
        "total_pages",
        "items_seen",
        "items_imported",
        "last_run_at",
        "last_success_at",
        "failure_count",
        "failure_kind",
    ):
        if field in values:
            setattr(state, field, values[field])
    await session.flush()
    return state


async def enrichment_stats(
    session: AsyncSession,
    *,
    rate_per_minute: int = 36,
    requests_per_title: int = 2,
) -> dict[str, Any]:
    """Aggregate backlog/retry counters for the admin panel and logs."""

    now = datetime.now(UTC)
    total = int((await session.scalar(select(func.count(Manga.id)))) or 0)
    pending_condition = _enrichment_pending_condition(now)
    available_condition = _enrichment_available_condition(now)
    retry_condition = and_(
        pending_condition, Manga.enrichment_retry_at > now
    )
    failed_condition = and_(
        pending_condition, Manga.enrichment_attempts >= ENRICHMENT_FAILED_ATTEMPTS
    )

    pending_total = int(
        (await session.scalar(select(func.count(Manga.id)).where(available_condition))) or 0
    )
    retrying_total = int(
        (await session.scalar(select(func.count(Manga.id)).where(retry_condition))) or 0
    )
    failed_total = int(
        (await session.scalar(select(func.count(Manga.id)).where(failed_condition))) or 0
    )
    oldest_pending = await session.scalar(
        select(func.min(Manga.created_at)).where(available_condition)
    )
    last_success = await session.scalar(select(func.max(Manga.last_synced_at)))

    source_rows: list[EnrichmentSourceStats] = []
    source_codes = [
        str(row[0])
        for row in (
            await session.execute(select(Manga.source).distinct().order_by(Manga.source))
        ).all()
    ]
    for source in source_codes:
        source_filter = Manga.source == source
        source_total = int(
            (await session.scalar(select(func.count(Manga.id)).where(source_filter))) or 0
        )
        source_pending = int(
            (
                await session.scalar(
                    select(func.count(Manga.id)).where(
                        source_filter, available_condition
                    )
                )
            )
            or 0
        )
        source_retrying = int(
            (
                await session.scalar(
                    select(func.count(Manga.id)).where(source_filter, retry_condition)
                )
            )
            or 0
        )
        source_failed = int(
            (
                await session.scalar(
                    select(func.count(Manga.id)).where(source_filter, failed_condition)
                )
            )
            or 0
        )
        source_last_success = await session.scalar(
            select(func.max(Manga.last_synced_at)).where(source_filter)
        )
        source_rows.append(
            EnrichmentSourceStats(
                source=source,
                total=source_total,
                pending=source_pending,
                retrying=source_retrying,
                failed=source_failed,
                last_success_at=source_last_success,
            )
        )

    estimated_seconds = 0
    if pending_total and rate_per_minute > 0:
        estimated_seconds = int(
            (pending_total * max(1, requests_per_title) / rate_per_minute) * 60
        )
    return {
        "total": total,
        "pending": pending_total,
        "retrying": retrying_total,
        "failed": failed_total,
        "oldest_pending_at": oldest_pending,
        "last_success_at": last_success,
        "requests_per_title": max(1, requests_per_title),
        "rate_per_minute": max(1, rate_per_minute),
        "estimated_seconds": estimated_seconds,
        "sources": source_rows,
    }


async def stats(session: AsyncSession) -> CatalogStats:
    manga_total = int((await session.scalar(select(func.count(Manga.id)))) or 0)
    chapter_total = int((await session.scalar(select(func.count(Chapter.id)))) or 0)
    now = datetime.now(UTC)
    pending_total = int(
        (
            await session.scalar(
                select(func.count(Manga.id)).where(_enrichment_available_condition(now))
            )
        )
        or 0
    )
    retrying_total = int(
        (
            await session.scalar(
                select(func.count(Manga.id)).where(
                    _enrichment_pending_condition(now),
                    Manga.enrichment_retry_at > now,
                )
            )
        )
        or 0
    )
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
    return CatalogStats(
        manga=manga_total,
        chapters=chapter_total,
        sources=sources,
        pending_enrichment=pending_total,
        retrying_enrichment=retrying_total,
    )


def _freshness_score(manga: Manga, now: datetime) -> float:
    moment = manga.last_chapter_at or manga.updated_at or manga.created_at
    if moment is None:
        return 0.25
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    age = (now - moment).total_seconds() / 86400
    if age <= 30:
        return 1.0
    if age <= 180:
        return 0.7
    if age <= 365:
        return 0.45
    return 0.2


def _recommendation_score(
    manga: Manga,
    *,
    weights: Counter[str],
    max_affinity: int,
    related: bool,
    now: datetime,
    personalized: bool,
    seed_only: bool,
) -> float:
    affinity = 0.0
    if max_affinity > 0:
        raw = sum(weights.get(slug, 0) for slug in genre_slugs(manga.genres or []))
        affinity = min(1.0, raw / max_affinity)
    rating = max(0.0, min(1.0, (manga.rating or 0.0) / 10.0))
    popularity = min(1.0, math.log1p(max(0, manga.rating_count or 0)) / 11.5)
    freshness = _freshness_score(manga, now)
    boost = 0.18 if related else 0.0
    if personalized:
        return 0.55 * affinity + 0.18 * rating + 0.12 * freshness + 0.10 * popularity + boost
    if seed_only:
        return 0.48 * affinity + 0.20 * rating + 0.20 * freshness + 0.12 * popularity + boost
    return 0.45 * rating + 0.30 * freshness + 0.25 * popularity


async def recommend_manga(
    session: AsyncSession,
    *,
    seed_manga_id: uuid.UUID | None = None,
    history_ids: list[uuid.UUID] | None = None,
    bookmark_ids: list[uuid.UUID] | None = None,
    exclude_ids: list[uuid.UUID] | None = None,
    limit: int = 12,
) -> tuple[list[Manga], str]:
    """Simple explainable recommendations from the local catalogue.

    Ranking uses genre affinity (history/bookmarks/seed), rating, freshness and
    popularity.  Read titles are excluded by id and by normalised title group so
    another source variant of an already-read title never appears.  Titles with
    no chapters are never recommended.
    """

    history = list(dict.fromkeys(history_ids or []))
    bookmarks = list(dict.fromkeys(bookmark_ids or []))
    explicit_excludes = list(dict.fromkeys(exclude_ids or []))
    focus_ids = list(dict.fromkeys(([seed_manga_id] if seed_manga_id else []) + history + bookmarks))
    excluded_ids = set(focus_ids + explicit_excludes)
    focus = list(
        (await session.scalars(select(Manga).where(Manga.id.in_(focus_ids)))).all()
    ) if focus_ids else []
    focus_by_id = {manga.id: manga for manga in focus}

    weights: Counter[str] = Counter()
    if seed_manga_id and seed_manga_id in focus_by_id:
        for slug in genre_slugs(focus_by_id[seed_manga_id].genres or []):
            weights[slug] += 3
    for manga_id in history:
        manga = focus_by_id.get(manga_id)
        if manga:
            for slug in genre_slugs(manga.genres or []):
                weights[slug] += 2
    for manga_id in bookmarks:
        manga = focus_by_id.get(manga_id)
        if manga:
            for slug in genre_slugs(manga.genres or []):
                weights[slug] += 1

    excluded_groups = {
        (manga.group_key or str(manga.id)) for manga in focus if manga.id in excluded_ids
    }
    for raw in explicit_excludes:
        row = await find_manga(session, raw)
        if row is not None:
            excluded_groups.add(row.group_key or str(row.id))

    related_ids: set[uuid.UUID] = set()
    if focus_ids:
        relation_rows = list(
            (
                await session.scalars(
                    select(MangaRelation).where(
                        or_(
                            MangaRelation.from_manga_id.in_(focus_ids),
                            MangaRelation.to_manga_id.in_(focus_ids),
                        )
                    )
                )
            ).all()
        )
        focus_set = set(focus_ids)
        for relation in relation_rows:
            if relation.from_manga_id in focus_set:
                related_ids.add(relation.to_manga_id)
            if relation.to_manga_id in focus_set:
                related_ids.add(relation.from_manga_id)
    related_ids -= excluded_ids

    conditions: list[Any] = [
        Manga.chapters_count > 0,
        exists(select(Chapter.id).where(Chapter.manga_id == Manga.id)),
    ]
    if excluded_ids:
        conditions.append(Manga.id.notin_(list(excluded_ids)))
    candidates = list(
        (
            await session.scalars(
                select(Manga)
                .where(*conditions)
                .order_by(
                    desc(Manga.rating_count),
                    desc(Manga.rating),
                    desc(Manga.last_chapter_at),
                    desc(Manga.updated_at),
                )
                .limit(500)
            )
        ).all()
    )

    now = datetime.now(UTC)
    max_affinity = max(weights.values(), default=0)
    personalized = bool(history or bookmarks)
    seed_only = bool(seed_manga_id and not personalized)
    scored: list[tuple[float, Manga]] = []
    seen_groups: set[str] = set()
    for manga in candidates:
        group = manga.group_key or str(manga.id)
        if manga.id in excluded_ids or group in excluded_groups or group in seen_groups:
            continue
        seen_groups.add(group)
        score = _recommendation_score(
            manga,
            weights=weights,
            max_affinity=max_affinity,
            related=manga.id in related_ids,
            now=now,
            personalized=personalized,
            seed_only=seed_only,
        )
        scored.append((score, manga))
    scored.sort(key=lambda item: (item[0], item[1].rating or 0), reverse=True)

    chosen: list[Manga] = []
    genre_counts: Counter[str] = Counter()
    # First pass keeps the shelf varied; a second pass fills the remainder from
    # any genre if the catalogue is too small.
    for _score, manga in scored:
        if len(chosen) >= limit:
            break
        slugs = genre_slugs(manga.genres or [])
        primary = slugs[0] if slugs else ""
        if primary and genre_counts[primary] >= 3:
            continue
        chosen.append(manga)
        if primary:
            genre_counts[primary] += 1
    if len(chosen) < limit:
        chosen_ids = {manga.id for manga in chosen}
        for _, manga in scored:
            if len(chosen) >= limit:
                break
            if manga.id not in chosen_ids:
                chosen.append(manga)
                chosen_ids.add(manga.id)

    if personalized:
        strategy = "personalized"
    elif seed_only:
        strategy = "related"
    else:
        strategy = "popular"
    return chosen, strategy


async def upsert_relation(
    session: AsyncSession,
    *,
    from_manga_id: uuid.UUID,
    to_manga_id: uuid.UUID,
    relation: str,
    series_key: str | None = None,
) -> MangaRelation:
    existing = await session.scalar(
        select(MangaRelation).where(
            MangaRelation.relation == relation,
            or_(
                and_(
                    MangaRelation.from_manga_id == from_manga_id,
                    MangaRelation.to_manga_id == to_manga_id,
                ),
                and_(
                    MangaRelation.from_manga_id == to_manga_id,
                    MangaRelation.to_manga_id == from_manga_id,
                ),
            ),
        )
    )
    normalized_key = (series_key or "").strip()[:180] or None
    if relation != "series":
        normalized_key = None
    if existing is None:
        existing = MangaRelation(
            from_manga_id=from_manga_id,
            to_manga_id=to_manga_id,
            relation=relation,
            series_key=normalized_key,
        )
        session.add(existing)
    elif normalized_key:
        existing.series_key = normalized_key
    await session.flush()
    return existing


async def manga_relations(
    session: AsyncSession, manga_id: uuid.UUID
) -> tuple[list[Manga], list[Manga]]:
    """Return explicit series and related titles for one manga page."""

    rows = list(
        (
            await session.scalars(
                select(MangaRelation).where(
                    or_(
                        MangaRelation.from_manga_id == manga_id,
                        MangaRelation.to_manga_id == manga_id,
                    )
                )
            )
        ).all()
    )
    series_keys = {
        row.series_key for row in rows if row.relation == "series" and row.series_key
    }
    if series_keys:
        extra = list(
            (
                await session.scalars(
                    select(MangaRelation).where(
                        MangaRelation.relation == "series",
                        MangaRelation.series_key.in_(series_keys),
                    )
                )
            ).all()
        )
        known = {(row.from_manga_id, row.to_manga_id, row.relation) for row in rows}
        rows.extend(
            row
            for row in extra
            if (row.from_manga_id, row.to_manga_id, row.relation) not in known
        )

    series_ids: set[uuid.UUID] = set()
    related_ids: set[uuid.UUID] = set()
    for row in rows:
        if row.relation == "series":
            series_ids.update({row.from_manga_id, row.to_manga_id})
        else:
            related_ids.update({row.from_manga_id, row.to_manga_id})
    series_ids.discard(manga_id)
    related_ids.discard(manga_id)
    related_ids -= series_ids
    ids = series_ids | related_ids
    if not ids:
        return [], []

    found = list(
        (
            await session.scalars(
                select(Manga)
                .where(
                    Manga.id.in_(ids),
                    Manga.chapters_count > 0,
                    exists(select(Chapter.id).where(Chapter.manga_id == Manga.id)),
                )
                .order_by(desc(Manga.rating), desc(Manga.rating_count), Manga.title.asc())
            )
        ).all()
    )
    by_id = {manga.id: manga for manga in found}
    series = [by_id[item] for item in series_ids if item in by_id]
    related = [by_id[item] for item in related_ids if item in by_id]
    return series, related


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
        chapters_count=manga.chapters_count,
    )
