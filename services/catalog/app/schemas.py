from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from manga_common.schemas import ChapterOut, MangaDetailOut
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


class SourceSyncRequest(BaseModel):
    sources: list[dict[str, Any]]


class CrawlStateIn(BaseModel):
    source: str = Field(min_length=1, max_length=64)
    mode: str = Field(default="full", pattern="^(full|incremental)$")
    page: int = Field(default=1, ge=1)
    status: str = Field(default="pending", max_length=24)
    last_error: str | None = Field(default=None, max_length=4000)
    next_run_at: datetime | None = None
    total_pages: int | None = Field(default=None, ge=0)
    items_seen: int = Field(default=0, ge=0)
    items_imported: int = Field(default=0, ge=0)
    last_run_at: datetime | None = None
    eta_seconds: int | None = Field(default=None, ge=0)


class CrawlStateOut(CrawlStateIn):
    id: UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None


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
