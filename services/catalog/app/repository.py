from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from manga_common.source_models import MangaDetail, MangaSummary, SourceInfo
from sqlalchemy import (
    Integer,
    String,
    and_,
    case,
    cast,
    desc,
    exists,
    func,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import Chapter, CrawlState, Manga, MangaCover, Source
from .normalization import (
    GENRE_LABELS,
    canonical_genre,
    genre_slugs,
    normalize_text,
    parse_genre_filter,
    status_key,
)
from .schemas import CatalogStats, SourceStats
from .search import (
    SearchQuery,
    analyze_query,
    dedupe_ranked_groups,
    expansion_terms,
    filter_relevant,
    fts_match_query,
    rank_rows,
    token_coverage,
)
from .search_fts import fts_available, sync_search_fts

DESCRIPTION_FALLBACK = "Упс. Описание не нашлось в источниках"
SEARCH_CANDIDATE_LIMIT = 300
SUGGESTION_CANDIDATE_LIMIT = 180


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
        variant.refresh_search_fields()
    for variant in variants:
        await sync_search_fts(session, variant.id, variant.search_blob)
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
    if detail.chapters_count is not None:
        manga.chapters_count = max(int(manga.chapters_count or 0), int(detail.chapters_count))
    manga.refresh_search_fields()
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
    await sync_search_fts(session, manga.id, manga.search_blob)
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
    manga.refresh_search_fields()
    await session.flush()

    await upsert_cover(session, manga, summary.poster_url or manga.poster_url)
    await merge_group_metadata(session, manga.group_key)
    await sync_search_fts(session, manga.id, manga.search_blob)
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
    source: str | None = None,
    genre: str | None = None,
    genres: list[str] | None = None,
    year: int | None = None,
    status: str | None = None,
    include_empty: bool = False,
) -> list[Any]:
    conditions: list[Any] = []
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


def _group_expr():
    return func.coalesce(func.nullif(Manga.group_key, ""), cast(Manga.id, String))


async def _search_filter(
    session: AsyncSession,
    query: SearchQuery,
    *,
    candidate_limit: int = SEARCH_CANDIDATE_LIMIT,
):
    """SQL candidate filter backed by FTS5 (SQLite), LIKE and trigram indexes."""

    dialect = session.get_bind().dialect.name
    if dialect == "sqlite" and await fts_available(session):
        match = fts_match_query(query)
        if not match:
            return None
        return text(
            "id IN (SELECT manga_id FROM manga_search_fts "
            "WHERE manga_search_fts MATCH :fts_query "
            "ORDER BY bm25(manga_search_fts) LIMIT :fts_limit)"
        ).bindparams(fts_query=match, fts_limit=candidate_limit)
    terms = expansion_terms(query, dialect=dialect)
    if not terms:
        return None
    return or_(*[Manga.search_blob.contains(term, autoescape=True) for term in terms])


def _candidate_order(query: SearchQuery):
    normalized = query.normalized
    preliminary = case(
        (Manga.search_title == normalized, 0),
        (Manga.search_title.startswith(normalized), 1),
        (Manga.search_names.contains(normalized, autoescape=True), 2),
        (Manga.search_blob.contains(normalized, autoescape=True), 3),
        else_=4,
    )
    return (
        preliminary,
        desc(Manga.chapters_count),
        desc(Manga.rating_count),
        desc(Manga.rating),
        desc(Manga.updated_at),
    )


async def search_manga(
    session: AsyncSession,
    query: SearchQuery,
    *,
    source: str | None = None,
    genre: str | None = None,
    genres: list[str] | None = None,
    year: int | None = None,
    status: str | None = None,
    include_empty: bool = False,
    page: int = 1,
    limit: int = 24,
) -> tuple[list[Manga], int]:
    """Rank local catalogue rows by relevance, then paginate title groups."""

    conditions = _manga_conditions(
        source=source,
        genre=genre,
        genres=genres,
        year=year,
        status=status,
        include_empty=include_empty,
    )
    search_filter = await _search_filter(session, query)
    if search_filter is None:
        return [], 0
    conditions.append(search_filter)

    candidates = list(
        (
            await session.scalars(
                select(Manga)
                .where(*conditions)
                .order_by(*_candidate_order(query))
                .limit(SEARCH_CANDIDATE_LIMIT)
            )
        ).all()
    )
    ranked = filter_relevant(dedupe_ranked_groups(rank_rows(query, candidates)))
    start = (page - 1) * limit
    items = [row for row, _score, _reason in ranked[start : start + limit]]
    return items, len(ranked)


async def suggest_manga(
    session: AsyncSession,
    raw_query: str,
    *,
    limit: int = 6,
) -> list[tuple[Manga, str]]:
    """Top local title suggestions.  This function never touches the parser."""

    query = analyze_query(raw_query)
    if query.is_empty:
        return []
    conditions = _manga_conditions(include_empty=False)
    search_filter = await _search_filter(
        session, query, candidate_limit=SUGGESTION_CANDIDATE_LIMIT
    )
    if search_filter is None:
        return []
    conditions.append(search_filter)
    candidates = list(
        (
            await session.scalars(
                select(Manga)
                .where(*conditions)
                .order_by(*_candidate_order(query))
                .limit(SUGGESTION_CANDIDATE_LIMIT)
            )
        ).all()
    )
    ranked = filter_relevant(dedupe_ranked_groups(rank_rows(query, candidates)))
    # Suggestions are a precision surface: a title that only shares one word
    # with a multi-word query should not sit next to the real answer.  Ranking
    # still scans the full filtered list, so this does not affect recall.
    need = len(query.tokens)
    result: list[tuple[Manga, str]] = []
    for row, _score, reason in ranked:
        if need > 1 and token_coverage(query, row) < need:
            continue
        result.append((row, reason))
        if len(result) >= limit:
            break
    return result


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
    search_query = analyze_query(query)
    if (query or "").strip() and search_query.is_empty:
        # A punctuation-only / stopword-only query must not silently turn into
        # an unfiltered catalogue dump.
        return [], 0
    if not search_query.is_empty:
        return await search_manga(
            session,
            search_query,
            source=source,
            genre=genre,
            genres=genres,
            year=year,
            status=status,
            include_empty=include_empty,
            page=page,
            limit=limit,
        )

    conditions = _manga_conditions(
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
    group_expr = _group_expr()
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
        manga.refresh_search_fields()
        await sync_search_fts(session, manga.id, manga.search_blob)
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


async def pending_enrichment(
    session: AsyncSession, *, source: str | None = None, limit: int = 50
) -> list[Manga]:
    """Titles discovered by the crawler but not yet hydrated with detail.

    ``last_synced_at`` is the primary marker, but old deployments also contain
    summaries that were marked synced while still having zero chapters.  Those
    are re-queued explicitly so the production QA dead-end cards heal after the
    first crawl pass.
    """

    conditions: list[Any] = [
        or_(
            Manga.last_synced_at.is_(None),
            and_(
                ~exists(select(Chapter.id).where(Chapter.manga_id == Manga.id)),
                or_(
                    Manga.last_synced_at.is_(None),
                    Manga.last_synced_at < datetime.now(UTC) - timedelta(hours=24),
                ),
            ),
        )
    ]
    if source:
        conditions.append(Manga.source == source)
    result = await session.scalars(
        select(Manga).where(*conditions).order_by(Manga.created_at.asc()).limit(limit)
    )
    return list(result.all())


async def reset_enrichment(session: AsyncSession, *, source: str | None = None) -> int:
    """Mark titles for a weekly full metadata refresh."""

    conditions = []
    if source:
        conditions.append(Manga.source == source)
    result = await session.execute(
        update(Manga).where(*conditions).values(last_synced_at=None)
    )
    await session.flush()
    return int(result.rowcount or 0)


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
    ):
        if field in values:
            setattr(state, field, values[field])
    await session.flush()
    return state


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
        chapters_count=manga.chapters_count,
    )
