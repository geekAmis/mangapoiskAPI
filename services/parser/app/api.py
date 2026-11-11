"""Internal parser HTTP API.

All routes require ``X-Internal-Token``.  The gateway/catalog are the only
intended callers; there is no public authentication or CORS story here.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from manga_common.errors import ValidationError as InputValidationError
from manga_common.security import require_internal_token
from manga_common.source_models import (
    ChapterDetail,
    MangaDetail,
    SourceHome,
    SourceInfo,
    SourceSearchResult,
)

from .adapters.base import BaseAdapter
from .registry import AdapterRegistry

router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(require_internal_token)],
)


def get_registry(request: Request) -> AdapterRegistry:
    registry = getattr(request.app.state, "registry", None)
    if not isinstance(registry, AdapterRegistry):
        raise RuntimeError("Adapter registry is not initialised")
    return registry


async def get_adapter(
    source: Annotated[str, Query(min_length=1, max_length=64)],
    registry: Annotated[AdapterRegistry, Depends(get_registry)],
) -> BaseAdapter:
    return registry.require(source)


@router.get("/sources", response_model=list[SourceInfo])
async def list_sources(
    registry: Annotated[AdapterRegistry, Depends(get_registry)],
) -> list[SourceInfo]:
    """List every known source, including disabled ones and their capabilities."""

    return registry.infos()


@router.get("/search", response_model=SourceSearchResult)
async def search(
    adapter: Annotated[BaseAdapter, Depends(get_adapter)],
    q: Annotated[str, Query(min_length=1, max_length=200)],
    page: Annotated[int, Query(ge=1, le=1000)] = 1,
) -> SourceSearchResult:
    """Search one source.  Pagination is adapter-specific."""

    return await adapter.search(q, page)


@router.get("/manga", response_model=MangaDetail)
async def manga(
    adapter: Annotated[BaseAdapter, Depends(get_adapter)],
    source_id: Annotated[str | None, Query(max_length=512)] = None,
    url: Annotated[str | None, Query(max_length=2048)] = None,
    chapters_limit: Annotated[int, Query(ge=0, le=1000)] = 100,
) -> MangaDetail:
    """Fetch manga details and up to ``chapters_limit`` chapters."""

    clean_id = (source_id or "").strip()
    clean_url = (url or "").strip()
    if not clean_id and not clean_url:
        raise InputValidationError(
            "Either source_id or url is required",
            code="missing_source_id",
        )
    return await adapter.get_manga(
        clean_id,
        url=clean_url or None,
        chapters_limit=chapters_limit,
    )


@router.get("/chapter", response_model=ChapterDetail)
async def chapter(
    adapter: Annotated[BaseAdapter, Depends(get_adapter)],
    source_id: Annotated[str | None, Query(max_length=512)] = None,
    url: Annotated[str | None, Query(max_length=2048)] = None,
) -> ChapterDetail:
    """Fetch one chapter and its page images."""

    clean_id = (source_id or "").strip()
    clean_url = (url or "").strip()
    if not clean_id and not clean_url:
        raise InputValidationError(
            "Either source_id or url is required",
            code="missing_source_id",
        )
    return await adapter.get_chapter(clean_id, url=clean_url or None)


@router.get("/home", response_model=SourceHome)
async def home(
    adapter: Annotated[BaseAdapter, Depends(get_adapter)],
) -> SourceHome:
    """Fetch the source's popular/latest landing lists."""

    return await adapter.latest()
