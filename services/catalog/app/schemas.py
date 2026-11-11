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


class CatalogStats(BaseModel):
    manga: int
    chapters: int
    sources: list[SourceStats]


class SourceSyncRequest(BaseModel):
    sources: list[dict[str, Any]]


class ChapterDetailInternal(ChapterOut):
    pages: list[dict[str, Any]] = Field(default_factory=list)
    prev_chapter_id: UUID | None = None
    next_chapter_id: UUID | None = None
    is_horizontal: bool = False
