from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from manga_common.errors import NotFoundError, ValidationError
from manga_common.text import slugify
from sqlalchemy import String, case, cast, delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    Chapter,
    CollectionAudit,
    Manga,
    MangaCollection,
    MangaCollectionItem,
)
from .normalization import genre_slugs
from .schemas import CollectionCreate, CollectionUpdate

# Built-in smart collections.  They are seeded once and can then be renamed,
# reordered, disabled or deleted in the admin panel; data regeneration never
# overwrites the editorial fields.
SMART_COLLECTIONS: tuple[dict[str, Any], ...] = (
    {
        "slug": "weekly-best",
        "title": "Лучшее за неделю",
        "description": "Высокий рейтинг и свежие главы за последние семь дней",
        "rule": "weekly_best",
        "position": 10,
    },
    {
        "slug": "beginners",
        "title": "Для новичков",
        "description": "Понятные жанры, ровный рейтинг и достаточно глав, чтобы втянуться",
        "rule": "beginners",
        "position": 20,
    },
    {
        "slug": "completed",
        "title": "Завершённые",
        "description": "Истории с финалом — можно читать без ожидания",
        "rule": "completed",
        "position": 30,
    },
    {
        "slug": "short",
        "title": "Короткие",
        "description": "До 30 глав: быстрый вечер вместо долгого сериала",
        "rule": "short",
        "position": 40,
    },
    {
        "slug": "new",
        "title": "Новые",
        "description": "Недавно появились в каталоге",
        "rule": "new",
        "position": 50,
    },
)

SMART_RULES = {item["rule"] for item in SMART_COLLECTIONS}
BEGINNER_GENRES = {
    "adventure",
    "comedy",
    "fantasy",
    "romance",
    "school",
    "slice-of-life",
    "sports",
    "supernatural",
}
MAX_COLLECTION_ITEMS = 60
ELIGIBLE_CANDIDATE_LIMIT = 600


def _group_expr():  # type: ignore[no-untyped-def]
    return func.coalesce(func.nullif(Manga.group_key, ""), cast(Manga.id, String))


def _nulls_last(column):  # type: ignore[no-untyped-def]
    """Portable ``DESC NULLS LAST``: PostgreSQL otherwise puts NULLs first."""

    return case((column.is_(None), 1), else_=0)


def _eligible():  # type: ignore[no-untyped-def]
    """A card is only publishable when it has a cover and at least one chapter."""

    return (
        Manga.chapters_count > 0,
        exists(select(Chapter.id).where(Chapter.manga_id == Manga.id)),
        Manga.poster_url.isnot(None),
        func.trim(Manga.poster_url) != "",
        func.trim(Manga.title) != "",
    )


def is_eligible(manga: Manga | None) -> bool:
    return bool(
        manga
        and manga.chapters_count > 0
        and (manga.poster_url or "").strip()
        and (manga.title or "").strip()
    )


def _dedupe(rows: list[Manga], *, limit: int, seen: set[str] | None = None) -> list[Manga]:
    """Keep the first (already ranked) variant of each title group."""

    groups = seen if seen is not None else set()
    result: list[Manga] = []
    for manga in rows:
        if len(result) >= limit:
            break
        if not is_eligible(manga):
            continue
        group = manga.group_key or str(manga.id)
        if group in groups:
            continue
        groups.add(group)
        result.append(manga)
    return result


async def _ranked(
    session: AsyncSession,
    *,
    conditions: tuple[Any, ...] = (),
    order: tuple[Any, ...],
    limit: int = ELIGIBLE_CANDIDATE_LIMIT,
) -> list[Manga]:
    rows = (
        await session.scalars(
            select(Manga)
            .where(*_eligible(), *conditions)
            .order_by(*order)
            .limit(limit)
        )
    ).all()
    return list(rows)


async def _smart_manga(
    session: AsyncSession,
    rule: str,
    *,
    limit: int,
    now: datetime | None = None,
) -> list[Manga]:
    moment = now or datetime.now(UTC)
    target = max(1, min(limit, MAX_COLLECTION_ITEMS))
    recent_order = (
        _nulls_last(Manga.rating),
        Manga.rating.desc(),
        _nulls_last(Manga.rating_count),
        Manga.rating_count.desc(),
        _nulls_last(Manga.last_chapter_at),
        Manga.last_chapter_at.desc(),
        Manga.title.asc(),
        Manga.id.asc(),
    )
    popularity_order = (
        _nulls_last(Manga.rating),
        Manga.rating.desc(),
        _nulls_last(Manga.rating_count),
        Manga.rating_count.desc(),
        Manga.chapters_count.desc(),
        Manga.title.asc(),
        Manga.id.asc(),
    )

    rows: list[Manga] = []
    if rule == "weekly_best":
        rows = await _ranked(
            session,
            conditions=(Manga.last_chapter_at >= moment - timedelta(days=7),),
            order=recent_order,
        )
        if len(rows) < target:
            rows.extend(
                await _ranked(
                    session,
                    conditions=(Manga.last_chapter_at >= moment - timedelta(days=30),),
                    order=recent_order,
                )
            )
    elif rule == "beginners":
        candidates = await _ranked(session, order=popularity_order)
        rows = [
            manga
            for manga in candidates
            if not manga.adult
            and (manga.rating or 0) >= 7.0
            and 10 <= (manga.chapters_count or 0) <= 500
            and BEGINNER_GENRES & set(genre_slugs(manga.genres or []))
        ]
        if len(rows) < target:
            rows.extend(
                manga
                for manga in candidates
                if not manga.adult and (manga.rating or 0) >= 6.5
            )
    elif rule == "completed":
        rows = await _ranked(
            session,
            conditions=(Manga.status_key == "completed",),
            order=popularity_order,
        )
    elif rule == "short":
        rows = await _ranked(
            session,
            conditions=(Manga.chapters_count > 0, Manga.chapters_count <= 30),
            order=recent_order,
        )
    elif rule == "new":
        rows = await _ranked(
            session,
            order=(
                Manga.created_at.desc(),
                _nulls_last(Manga.rating),
                Manga.rating.desc(),
                _nulls_last(Manga.rating_count),
                Manga.rating_count.desc(),
                Manga.title.asc(),
                Manga.id.asc(),
            ),
        )

    chosen = _dedupe(rows, limit=target)
    if not chosen and rule in {"weekly_best", "beginners"}:
        # Cold-start fallback for the two broad discovery shelves.  The
        # rule-specific shelves ("completed", "short", "new") are never
        # back-filled with titles that violate their promise: an empty shelf is
        # omitted by the public API and the home page keeps its other sections.
        fallback = await _ranked(session, order=popularity_order)
        chosen = _dedupe(fallback, limit=target)
    return chosen


async def seed_smart_collections(session: AsyncSession) -> int:
    """Seed the built-in shelves on a fresh catalogue only.

    The table is seeded once.  A later restart must not resurrect a shelf the
    editor deliberately deleted, and must not overwrite renamed/reordered rows.
    """

    existing_count = await session.scalar(select(func.count()).select_from(MangaCollection))
    if existing_count:
        return 0
    created = 0
    for spec in SMART_COLLECTIONS:
        session.add(
            MangaCollection(
                slug=str(spec["slug"]),
                title=str(spec["title"]),
                description=str(spec["description"]),
                kind="smart",
                rule=str(spec["rule"]),
                enabled=True,
                position=int(spec["position"]),
                limit=12,
            )
        )
        created += 1
    if created:
        await session.flush()
    return created


async def list_collections(session: AsyncSession, *, enabled_only: bool = False) -> list[MangaCollection]:
    conditions = [MangaCollection.enabled.is_(True)] if enabled_only else []
    rows = await session.scalars(
        select(MangaCollection)
        .where(*conditions)
        .order_by(
            MangaCollection.position.asc(),
            MangaCollection.title.asc(),
            MangaCollection.id.asc(),
        )
    )
    return list(rows.all())


async def find_collection(session: AsyncSession, collection_id: uuid.UUID) -> MangaCollection | None:
    return await session.get(MangaCollection, collection_id)


async def find_collection_by_slug(session: AsyncSession, slug: str) -> MangaCollection | None:
    return await session.scalar(
        select(MangaCollection).where(MangaCollection.slug == slug)
    )


async def collection_manga(
    session: AsyncSession,
    collection: MangaCollection,
    *,
    limit: int | None = None,
    fallback: bool = True,
) -> list[Manga]:
    target = max(1, min(limit or collection.limit or 12, MAX_COLLECTION_ITEMS))
    if collection.kind == "smart" and collection.rule in SMART_RULES:
        return await _smart_manga(session, str(collection.rule), limit=target)
    rows = list(
        (
            await session.scalars(
                select(Manga)
                .join(MangaCollectionItem, MangaCollectionItem.manga_id == Manga.id)
                .where(*_eligible(), MangaCollectionItem.collection_id == collection.id)
                .order_by(
                    MangaCollectionItem.position.asc(),
                    MangaCollectionItem.created_at.asc(),
                    Manga.title.asc(),
                    Manga.id.asc(),
                )
                .limit(MAX_COLLECTION_ITEMS)
            )
        ).all()
    )
    # Manual shelves keep their order and are never back-filled: an empty
    # editorial collection must stay visibly empty rather than show random
    # titles the editor did not choose.
    return _dedupe(rows, limit=target)


async def _unique_slug(session: AsyncSession, title: str, requested: str | None) -> str:
    base = slugify((requested or title).strip())[:48].strip("-") or "collection"
    candidate = base
    suffix = 2
    while await find_collection_by_slug(session, candidate) is not None:
        candidate = f"{base}-{suffix}"
        suffix += 1
        if len(candidate) > 64:
            candidate = f"{base[:56]}-{suffix}"
    return candidate


async def create_collection(session: AsyncSession, payload: CollectionCreate) -> MangaCollection:
    kind = payload.kind
    rule = payload.rule
    title = payload.title.strip()
    if not title:
        raise ValidationError(
            "Название подборки не может быть пустым", code="collection_title_required"
        )
    if kind == "smart" and rule is None:
        raise ValidationError("Умной подборке нужно правило", code="collection_rule_required")
    if kind == "manual":
        rule = None
    collection = MangaCollection(
        slug=await _unique_slug(session, title, payload.slug),
        title=title,
        description=payload.description.strip(),
        kind=kind,
        rule=rule,
        enabled=payload.enabled,
        position=payload.position,
        limit=payload.limit,
    )
    session.add(collection)
    await session.flush()
    await record_collection_audit(
        session,
        "collection.created",
        collection_id=collection.id,
        details={"slug": collection.slug, "title": collection.title, "kind": collection.kind},
    )
    return collection


async def update_collection(
    session: AsyncSession,
    collection: MangaCollection,
    payload: CollectionUpdate,
) -> MangaCollection:
    values = payload.model_dump(exclude_unset=True)
    if "title" in values and values["title"] is not None:
        collection.title = str(values["title"]).strip()
        if not collection.title:
            raise ValidationError(
                "Название подборки не может быть пустым", code="collection_title_required"
            )
    if "slug" in values and values["slug"] is not None:
        desired = slugify(str(values["slug"]))[:64].strip("-")
        if not desired:
            raise ValidationError("Некорректный slug подборки", code="collection_slug_invalid")
        existing = await find_collection_by_slug(session, desired)
        if existing is not None and existing.id != collection.id:
            raise ValidationError("Подборка с таким slug уже существует", code="collection_slug_taken")
        collection.slug = desired
    if "description" in values and values["description"] is not None:
        collection.description = str(values["description"]).strip()
    if "kind" in values and values["kind"] is not None:
        collection.kind = str(values["kind"])
    if "rule" in values:
        collection.rule = values["rule"]
    if collection.kind == "smart":
        if collection.rule not in SMART_RULES:
            raise ValidationError("Неизвестное правило подборки", code="collection_rule_invalid")
    else:
        collection.rule = None
    if "enabled" in values and values["enabled"] is not None:
        collection.enabled = bool(values["enabled"])
    if "position" in values and values["position"] is not None:
        collection.position = int(values["position"])
    if "limit" in values and values["limit"] is not None:
        collection.limit = max(1, min(int(values["limit"]), MAX_COLLECTION_ITEMS))
    await session.flush()
    await record_collection_audit(
        session,
        "collection.updated",
        collection_id=collection.id,
        details={
            "slug": collection.slug,
            "title": collection.title,
            "enabled": collection.enabled,
            "position": collection.position,
        },
    )
    return collection


async def delete_collection(session: AsyncSession, collection: MangaCollection) -> None:
    details = {"slug": collection.slug, "title": collection.title, "kind": collection.kind}
    collection_id = collection.id
    # SQLite does not enable foreign-key cascades by default, and production
    # Postgres does.  Delete the children explicitly so both dialects leave no
    # orphaned rows behind.
    await session.execute(
        delete(MangaCollectionItem).where(MangaCollectionItem.collection_id == collection_id)
    )
    await session.delete(collection)
    await session.flush()
    await record_collection_audit(
        session,
        "collection.deleted",
        collection_id=collection_id,
        details=details,
    )


async def add_collection_item(
    session: AsyncSession,
    collection: MangaCollection,
    manga_id: uuid.UUID,
) -> bool:
    manga = await session.get(Manga, manga_id)
    if manga is None:
        raise NotFoundError("Тайтл не найден")
    if not is_eligible(manga):
        raise ValidationError(
            "В подборку можно добавить только тайтл с обложкой и главами",
            code="collection_item_ineligible",
        )
    has_chapters = await session.scalar(
        select(Chapter.id).where(Chapter.manga_id == manga.id).limit(1)
    )
    if has_chapters is None:
        raise ValidationError(
            "В подборку можно добавить только тайтл с обложкой и главами",
            code="collection_item_ineligible",
        )
    existing = await session.scalar(
        select(MangaCollectionItem).where(
            MangaCollectionItem.collection_id == collection.id,
            MangaCollectionItem.manga_id == manga_id,
        )
    )
    if existing is not None:
        return False
    last_position = await session.scalar(
        select(func.max(MangaCollectionItem.position)).where(
            MangaCollectionItem.collection_id == collection.id
        )
    )
    session.add(
        MangaCollectionItem(
            collection_id=collection.id,
            manga_id=manga_id,
            position=int(last_position or 0) + 10,
        )
    )
    await session.flush()
    await record_collection_audit(
        session,
        "collection.item_added",
        collection_id=collection.id,
        details={"slug": collection.slug, "manga_id": str(manga_id), "manga_title": manga.title},
    )
    return True


async def remove_collection_item(
    session: AsyncSession,
    collection: MangaCollection,
    manga_id: uuid.UUID,
) -> bool:
    item = await session.scalar(
        select(MangaCollectionItem).where(
            MangaCollectionItem.collection_id == collection.id,
            MangaCollectionItem.manga_id == manga_id,
        )
    )
    if item is None:
        return False
    manga = await session.get(Manga, manga_id)
    await session.delete(item)
    await session.flush()
    await record_collection_audit(
        session,
        "collection.item_removed",
        collection_id=collection.id,
        details={
            "slug": collection.slug,
            "manga_id": str(manga_id),
            "manga_title": manga.title if manga else "",
        },
    )
    return True


async def reorder_collection_items(
    session: AsyncSession,
    collection: MangaCollection,
    manga_ids: list[uuid.UUID],
) -> int:
    rows = list(
        (
            await session.scalars(
                select(MangaCollectionItem)
                .where(MangaCollectionItem.collection_id == collection.id)
                .order_by(
                    MangaCollectionItem.position.asc(),
                    MangaCollectionItem.created_at.asc(),
                    MangaCollectionItem.id.asc(),
                )
            )
        ).all()
    )
    by_manga = {row.manga_id: row for row in rows}
    ordered: list[MangaCollectionItem] = []
    for manga_id in manga_ids:
        row = by_manga.pop(manga_id, None)
        if row is not None:
            ordered.append(row)
    ordered.extend(by_manga.values())
    for index, row in enumerate(ordered):
        row.position = index * 10
    await session.flush()
    await record_collection_audit(
        session,
        "collection.reordered",
        collection_id=collection.id,
        details={"slug": collection.slug, "order": [str(item) for item in manga_ids]},
    )
    return len(ordered)


async def record_collection_audit(
    session: AsyncSession,
    action: str,
    *,
    collection_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    session.add(
        CollectionAudit(
            action=action,
            collection_id=collection_id,
            details=details or {},
        )
    )
    await session.flush()


async def list_collection_audit(session: AsyncSession, *, limit: int = 100) -> list[CollectionAudit]:
    rows = await session.scalars(
        select(CollectionAudit).order_by(CollectionAudit.created_at.desc()).limit(max(1, min(limit, 500)))
    )
    return list(rows.all())


async def _focus_groups(
    session: AsyncSession,
    ids: list[uuid.UUID],
) -> set[str]:
    if not ids:
        return set()
    rows = await session.scalars(select(Manga).where(Manga.id.in_(ids)))
    return {manga.group_key or str(manga.id) for manga in rows}


def _closeness(left: int, right: int) -> float:
    if left <= 0 or right <= 0:
        return 0.0
    return max(
        0.0,
        1.0 - min(abs(math.log1p(left) - math.log1p(right)) / 2.6, 1.0),
    )


def similar_score(seed: Manga, manga: Manga) -> float:
    """Deterministic, explainable similarity in ``0..1``.

    Weights follow the issue: genres dominate, then rating, release year,
    content type and chapter-count closeness.  Popularity is only a tie-breaker.
    """

    seed_genres = set(genre_slugs(seed.genres or []))
    other_genres = set(genre_slugs(manga.genres or []))
    union = seed_genres | other_genres
    genre = len(seed_genres & other_genres) / len(union) if union else 0.0

    rating = max(0.0, min(1.0, (manga.rating or 0.0) / 10.0))
    if seed.year and manga.year:
        year = max(0.0, 1.0 - min(abs(seed.year - manga.year) / 20.0, 1.0))
    else:
        year = 0.25
    type_match = (
        1.0
        if (seed.content_type or "").strip().casefold() == (manga.content_type or "").strip().casefold()
        and (seed.content_type or "").strip()
        else 0.0
    )
    chapters = _closeness(int(seed.chapters_count or 0), int(manga.chapters_count or 0))
    popularity = min(1.0, math.log1p(max(0, manga.rating_count or 0)) / 11.5)
    return (
        0.52 * genre
        + 0.18 * rating
        + 0.10 * year
        + 0.08 * type_match
        + 0.07 * chapters
        + 0.05 * popularity
    )


async def similar_manga(
    session: AsyncSession,
    seed: Manga,
    *,
    history_ids: list[uuid.UUID] | None = None,
    exclude_ids: list[uuid.UUID] | None = None,
    limit: int = 12,
) -> list[Manga]:
    """Find 6–12 clean, deterministic look-alikes for one title.

    The seed itself, other source variants of the seed or a read title, empty
    stubs, titles without covers and explicitly excluded ids are never returned.
    """

    target = max(6, min(limit, 12))
    history = list(dict.fromkeys(history_ids or []))
    explicit = list(dict.fromkeys(exclude_ids or []))
    excluded_ids = {seed.id, *history, *explicit}
    excluded_groups = await _focus_groups(session, [seed.id, *history])
    excluded_groups.add(seed.group_key or str(seed.id))
    for manga_id in explicit:
        row = await session.get(Manga, manga_id)
        if row is not None:
            excluded_groups.add(row.group_key or str(row.id))

    conditions: list[Any] = [Manga.id.notin_(list(excluded_ids))]
    if excluded_groups:
        conditions.append(_group_expr().notin_(list(excluded_groups)))
    candidates = list(
        (
            await session.scalars(
                select(Manga)
                .where(*_eligible(), *conditions)
                .order_by(
                    _nulls_last(Manga.rating_count),
                    Manga.rating_count.desc(),
                    _nulls_last(Manga.rating),
                    Manga.rating.desc(),
                    Manga.chapters_count.desc(),
                    Manga.title.asc(),
                    Manga.id.asc(),
                )
                .limit(ELIGIBLE_CANDIDATE_LIMIT)
            )
        ).all()
    )

    scored: list[tuple[float, Manga]] = []
    seen_groups: set[str] = set()
    for manga in candidates:
        group = manga.group_key or str(manga.id)
        if group in excluded_groups or group in seen_groups:
            continue
        seen_groups.add(group)
        scored.append((similar_score(seed, manga), manga))

    scored.sort(
        key=lambda item: (
            -item[0],
            -(item[1].rating or 0),
            -(item[1].rating_count or 0),
            item[1].title.casefold(),
            str(item[1].id),
        )
    )
    return [manga for _score, manga in scored[:target]]
