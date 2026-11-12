from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from manga_common.schemas import ChapterOut, MangaDetailOut, MangaOut
from pydantic import BaseModel, Field


class ImportRequest(BaseModel):
    source: str = Field(min_length=1, max_length=64)
    source_id: str | None = Field(default=None, max_length=512)
    url: str | None = Field(default=None, max_length=2048)
    refresh: bool = True


class ImportResult(BaseModel):
    manga: MangaDetailOut
    source: str
    created: bool = False
    imported_chapters: int = 0
    imported_pages: int = 0
    new_chapters: list[ChapterOut] = Field(default_factory=list)


class PagesPatch(BaseModel):
    pages: list[dict[str, Any]]
    is_horizontal: bool = False
    page_count: int | None = None


class NewChapterEvent(BaseModel):
    manga_id: UUID
    manga_title: str
    chapter_id: UUID
    chapter_label: str
    source: str
    url: str | None = None
    published_at: datetime | None = None


class RefreshResult(BaseModel):
    refreshed: int
    failed: int
    new_chapters: list[NewChapterEvent] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class SourceStats(BaseModel):
    source: str
    manga: int
    chapters: int
    pending: int = 0


class CatalogStats(BaseModel):
    manga: int
    chapters: int
    pending: int = 0
    sources: list[SourceStats]
    pending_enrichment: int = 0
    retrying_enrichment: int = 0


class SourceSyncRequest(BaseModel):
    sources: list[dict[str, Any]]


class CrawlStateIn(BaseModel):
    source: str = Field(min_length=1, max_length=64)
    mode: str = Field(
        default="full", pattern="^(full|incremental|health|enrichment)$"
    )
    page: int = Field(default=1, ge=0)
    status: str = Field(default="pending", max_length=24)
    last_error: str | None = Field(default=None, max_length=4000)
    next_run_at: datetime | None = None
    total_pages: int | None = Field(default=None, ge=0)
    items_seen: int = Field(default=0, ge=0)
    items_imported: int = Field(default=0, ge=0)
    last_run_at: datetime | None = None
    last_success_at: datetime | None = None
    failure_count: int = Field(default=0, ge=0)
    failure_kind: str | None = Field(default=None, max_length=32)
    eta_seconds: int | None = Field(default=None, ge=0)


class CrawlStateOut(CrawlStateIn):
    id: UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None


class EnrichmentSourceStats(BaseModel):
    source: str
    total: int = 0
    pending: int = 0
    retrying: int = 0
    failed: int = 0
    last_success_at: datetime | None = None


class EnrichmentStats(BaseModel):
    total: int = 0
    pending: int = 0
    retrying: int = 0
    failed: int = 0
    oldest_pending_at: datetime | None = None
    last_success_at: datetime | None = None
    requests_per_title: int = 2
    rate_per_minute: int = 36
    estimated_seconds: int = 0
    sources: list[EnrichmentSourceStats] = Field(default_factory=list)


class EnrichmentFailureRequest(BaseModel):
    error: str = Field(default="", max_length=4000)
    kind: str = Field(default="transient", max_length=32)
    permanent: bool = False


class GenreOut(BaseModel):
    slug: str
    label: str
    count: int = 0
    aliases: list[str] = Field(default_factory=list)


class GenreListOut(BaseModel):
    items: list[GenreOut] = Field(default_factory=list)
    total: int = 0


class HomeUpdateOut(BaseModel):
    manga_id: UUID
    manga_title: str
    poster_url: str | None = None
    source: str
    chapter_id: UUID
    chapter_number: str
    chapter_volume: str | None = None
    chapter_title: str = ""
    published_at: datetime | None = None
    added_at: datetime | None = None


class HomeUpdatesOut(BaseModel):
    items: list[HomeUpdateOut] = Field(default_factory=list)
    total: int = 0


class PendingEnrichmentOut(BaseModel):
    manga_id: UUID
    source: str
    source_id: str
    title: str
    url: str | None = None


class PendingEnrichmentListOut(BaseModel):
    items: list[PendingEnrichmentOut] = Field(default_factory=list)
    total: int = 0


class ChapterDetailInternal(ChapterOut):
    pages: list[dict[str, Any]] = Field(default_factory=list)
    prev_chapter_id: UUID | None = None
    next_chapter_id: UUID | None = None
    is_horizontal: bool = False


class RecommendationRequest(BaseModel):
    seed_manga_id: UUID | None = None
    history_ids: list[UUID] = Field(default_factory=list, max_length=100)
    bookmark_ids: list[UUID] = Field(default_factory=list, max_length=100)
    exclude_ids: list[UUID] = Field(default_factory=list, max_length=100)
    limit: int = Field(default=12, ge=1, le=24)


class RecommendationResult(BaseModel):
    items: list[MangaOut] = Field(default_factory=list)
    strategy: Literal["personalized", "popular", "related"] = "popular"


class RelationIn(BaseModel):
    to_manga_id: UUID
    relation: Literal["series", "related"] = "related"
    series_key: str | None = Field(default=None, max_length=180)


class RelationsIn(BaseModel):
    items: list[RelationIn] = Field(default_factory=list, max_length=50)


class RelationsOut(BaseModel):
    linked: int = 0
