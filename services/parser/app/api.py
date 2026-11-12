"""Internal parser HTTP API.

All routes require ``X-Internal-Token``.  The gateway/catalog are the only
intended callers; there is no public authentication or CORS story here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from manga_common.errors import NotFoundError
from manga_common.errors import ValidationError as InputValidationError
from manga_common.security import require_internal_token
from manga_common.source_models import (
    ChapterDetail,
    MangaDetail,
    SourceHome,
    SourceInfo,
    SourceSearchResult,
)
from pydantic import BaseModel, Field

from .adapters.base import BaseAdapter
from .cookie_store import (
    MAX_COOKIE_LENGTH,
    SourceCookieStore,
    apply_cookie,
    cookie_supported,
)
from .registry import AdapterRegistry

router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(require_internal_token)],
)


class SourceCookieStatus(BaseModel):
    """Public (non-secret) state of one source credential."""

    source: str
    configured: bool
    supported: bool = True
    updated_at: datetime | None = None


class SourceCookieUpdate(BaseModel):
    """Admin-supplied credential; never echoed back by the API."""

    cookie: str = Field(default="", max_length=MAX_COOKIE_LENGTH)


def get_registry(request: Request) -> AdapterRegistry:
    registry = getattr(request.app.state, "registry", None)
    if not isinstance(registry, AdapterRegistry):
        raise RuntimeError("Adapter registry is not initialised")
    return registry


def get_cookie_store(request: Request) -> SourceCookieStore:
    store = getattr(request.app.state, "cookie_store", None)
    if not isinstance(store, SourceCookieStore):
        raise RuntimeError("Source cookie store is not initialised")
    return store


def _known_adapter(registry: AdapterRegistry, code: str) -> BaseAdapter:
    normalised = (code or "").strip().lower()
    if normalised not in registry.codes():
        raise NotFoundError(
            f"Unknown source '{code}'",
            code="source_not_found",
            details={"available": sorted(registry.codes())},
        )
    adapter = registry.get(normalised)
    if adapter is None:  # pragma: no cover - defensive; codes() and get() agree
        raise NotFoundError(
            f"Unknown source '{code}'",
            code="source_not_found",
            details={"available": sorted(registry.codes())},
        )
    return adapter


def _cookie_status(
    adapter: BaseAdapter,
    store: SourceCookieStore,
) -> SourceCookieStatus:
    record = store.get(adapter.info.code)
    return SourceCookieStatus(
        source=adapter.info.code,
        configured=record is not None,
        supported=cookie_supported(adapter),
        updated_at=record.updated_at if record is not None else None,
    )


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


@router.get("/sources/{code}/cookie", response_model=SourceCookieStatus)
async def get_source_cookie(
    code: str,
    registry: Annotated[AdapterRegistry, Depends(get_registry)],
    store: Annotated[SourceCookieStore, Depends(get_cookie_store)],
) -> SourceCookieStatus:
    """Report whether a source credential is configured.

    The credential value is deliberately never returned, masked or logged.
    """

    adapter = _known_adapter(registry, code)
    return _cookie_status(adapter, store)


@router.put("/sources/{code}/cookie", response_model=SourceCookieStatus)
async def put_source_cookie(
    code: str,
    payload: SourceCookieUpdate,
    registry: Annotated[AdapterRegistry, Depends(get_registry)],
    store: Annotated[SourceCookieStore, Depends(get_cookie_store)],
) -> SourceCookieStatus:
    """Store/replace a source credential and update the live adapter.

    An empty ``cookie`` clears the stored value.  The request body and value are
    never logged by this endpoint.
    """

    adapter = _known_adapter(registry, code)
    if not cookie_supported(adapter):
        raise InputValidationError(
            f"Source '{adapter.info.code}' does not support runtime cookies",
            code="cookie_not_supported",
            details={"source": adapter.info.code},
        )

    value = payload.cookie.strip()
    try:
        await store.set(adapter.info.code, value)
    except ValueError as exc:
        raise InputValidationError(str(exc), code="invalid_cookie") from exc

    # Apply to the already-constructed adapter so no restart is required.
    apply_cookie(adapter, value or None)
    return _cookie_status(adapter, store)
