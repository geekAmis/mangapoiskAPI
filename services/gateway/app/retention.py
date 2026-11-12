from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from manga_common.schemas import (
    AnalyticsEventsIn,
    AnalyticsIngestOut,
    AnalyticsRetentionOut,
    ProgressMergeOut,
    ProgressMergeRequest,
    RecommendationListOut,
    RelatedMangaOut,
    StreakOut,
)
from manga_common.security import UserClaims, optional_user, require_admin, require_user
from pydantic import BaseModel, Field

from .clients import CatalogClient, LibraryClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")

MAX_SEED_IDS = 50


class RelationIn(BaseModel):
    to_manga_id: uuid.UUID
    relation: Literal["series", "related"] = "related"
    series_key: str | None = Field(default=None, max_length=180)


class RelationsIn(BaseModel):
    items: list[RelationIn] = Field(default_factory=list, max_length=50)


def _clients(request: Request) -> tuple[CatalogClient, LibraryClient]:
    return request.app.state.catalog, request.app.state.library


def _authorization(request: Request) -> str:
    return request.headers.get("Authorization", "")


def _parse_ids(raw: str | None, *, limit: int = MAX_SEED_IDS) -> list[uuid.UUID]:
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


@router.get("/recommendations", response_model=RecommendationListOut)
async def recommendations(
    request: Request,
    response: Response,
    limit: int = Query(default=12, ge=1, le=24),
    seed_manga_id: uuid.UUID | None = Query(default=None),
    seed_ids: str | None = Query(default=None, max_length=1800),
    exclude: str | None = Query(default=None, max_length=1800),
    user: Annotated[UserClaims | None, Depends(optional_user)] = None,
) -> RecommendationListOut:
    """Personal recommendations with a cold-start fallback.

    Authenticated users get genre affinity from account history/bookmarks.
    Anonymous clients may send their local read ids via ``seed_ids`` and
    ``exclude``; the endpoint itself is public and never requires a session.
    """

    catalog, library = _clients(request)
    history_ids: list[uuid.UUID] = []
    bookmark_ids: list[uuid.UUID] = []
    if user is not None:
        try:
            items = await library.history(_authorization(request), limit=100)
            history_ids = [item.manga_id for item in items]
            bookmarks = await library.bookmarks(_authorization(request))
            bookmark_ids = [item.manga_id for item in bookmarks]
        except Exception as exc:
            logger.debug("recommendation history unavailable: %s", exc)

    local_seeds = _parse_ids(seed_ids)
    local_excludes = _parse_ids(exclude)
    # For anonymous clients seed_ids are the only history available.  They both
    # drive genre affinity and must be excluded from the answer.
    all_history = list(dict.fromkeys([*history_ids, *local_seeds]))
    result = await catalog.recommendations(
        {
            "seed_manga_id": str(seed_manga_id) if seed_manga_id else None,
            "history_ids": [str(item) for item in all_history],
            "bookmark_ids": [str(item) for item in bookmark_ids],
            "exclude_ids": [str(item) for item in [*local_seeds, *local_excludes]],
            "limit": limit,
        }
    )
    # Personal shelves are private; the anonymous fallback can be shared by a
    # short-lived edge cache without leaking anyone's reading history.
    response.headers["Cache-Control"] = (
        "private, max-age=60" if user is not None else "public, max-age=60"
    )
    return result


@router.get("/manga/{manga_id}/related", response_model=RelatedMangaOut)
async def related_manga(request: Request, manga_id: uuid.UUID) -> RelatedMangaOut:
    catalog, _ = _clients(request)
    return await catalog.related(str(manga_id))


@router.put("/admin/manga/{manga_id}/relations")
async def link_relations(
    request: Request,
    manga_id: uuid.UUID,
    payload: RelationsIn,
    user: UserClaims = Depends(require_admin),
) -> dict[str, Any]:
    """Explicit admin/seed hook for series and related links.

    No title is linked automatically: a wrong cycle is a data decision that must
    be reviewed, not an inference made from similar titles.
    """

    catalog, _ = _clients(request)
    return await catalog.link_relations(
        str(manga_id), {"items": [item.model_dump(mode="json") for item in payload.items]}
    )


@router.post("/library/progress/merge", response_model=ProgressMergeOut)
async def merge_progress(
    request: Request,
    payload: ProgressMergeRequest,
    user: UserClaims = Depends(require_user),
) -> ProgressMergeOut:
    _, library = _clients(request)
    return await library.merge_progress(_authorization(request), payload.model_dump(mode="json"))


@router.get("/library/streak", response_model=StreakOut)
async def reading_streak(
    request: Request,
    timezone: str | None = Query(default=None, max_length=64),
    user: UserClaims = Depends(require_user),
) -> StreakOut:
    _, library = _clients(request)
    return await library.streak(_authorization(request), timezone)


@router.post("/analytics/events", response_model=AnalyticsIngestOut)
async def ingest_analytics(
    request: Request,
    payload: AnalyticsEventsIn,
) -> AnalyticsIngestOut:
    """Public, privacy-friendly event ingestion.

    The browser sends only an event name, random device id and optional
    catalogue ids.  The gateway does not forward IP addresses or user agents.
    """

    _, library = _clients(request)
    return await library.ingest_analytics(payload.model_dump(mode="json"))


@router.get("/admin/analytics/retention", response_model=AnalyticsRetentionOut)
async def analytics_retention(
    request: Request,
    days: int = Query(default=30, ge=1, le=90),
    user: UserClaims = Depends(require_admin),
) -> AnalyticsRetentionOut:
    _, library = _clients(request)
    return await library.analytics_retention(days)
