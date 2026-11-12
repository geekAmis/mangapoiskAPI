"""Normalised source contracts.

Adapters in ``services/parser`` translate each upstream website into these
models.  Nothing outside the parser service should know about HTML selectors or
private website JSON shapes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class SourceCapabilities(BaseModel):
    search: bool = False
    catalog: bool = False
    manga: bool = False
    chapters: bool = False
    pages: bool = False
    latest: bool = False
    requires_auth_for_pages: bool = False


class SourceInfo(BaseModel):
    code: str
    name: str
    base_url: str
    language: str = "ru"
    enabled: bool = True
    requires_cookies: bool = False
    # Adult-only sources are never exposed to guests or users who have not
    # confirmed they are 18+.  ``requires_age_confirmation`` is the stricter
    # per-title flag used by the catalogue and gateway.
    adult_only: bool = False
    requires_age_confirmation: bool = False
    capabilities: SourceCapabilities = Field(default_factory=SourceCapabilities)
    notes: str | None = None


class ChapterSummary(BaseModel):
    source: str
    source_id: str
    manga_source_id: str
    volume: str | None = None
    number: str
    title: str = ""
    translator: str | None = None
    published_at: datetime | None = None
    page_count: int = 0
    url: str | None = None
    is_external: bool = False

    @property
    def display_number(self) -> str:
        if self.volume:
            return f"Том {self.volume}, глава {self.number}"
        return f"Глава {self.number}"


class MangaSummary(BaseModel):
    source: str
    source_id: str
    slug: str | None = None
    title: str
    title_en: str | None = None
    title_alt: str | None = None
    description: str | None = None
    year: int | None = None
    status: str | None = None
    content_type: str | None = None
    rating: float | None = None
    rating_count: int | None = None
    poster_url: str | None = None
    adult: bool = False
    adult_only: bool = False
    requires_age_confirmation: bool = False
    genres: list[str] = Field(default_factory=list)
    url: str | None = None
    updated_at: datetime | None = None
    latest_chapter: ChapterSummary | None = None
    # Catalogue cards expose this without a detail request on MangaPoisk.
    chapters_count: int | None = None


class MangaDetail(MangaSummary):
    chapters: list[ChapterSummary] = Field(default_factory=list)


class Page(BaseModel):
    number: int
    url: str
    width: int | None = None
    height: int | None = None


class ChapterDetail(BaseModel):
    chapter: ChapterSummary
    pages: list[Page] = Field(default_factory=list)
    prev_url: str | None = None
    next_url: str | None = None
    is_horizontal: bool = False


class SourceSearchResult(BaseModel):
    source: str
    items: list[MangaSummary] = Field(default_factory=list)
    page: int = 1
    total: int | None = None
    has_next: bool = False
    total_pages: int | None = None
    per_page: int | None = None


class SourceHome(BaseModel):
    source: str
    popular: list[MangaSummary] = Field(default_factory=list)
    latest: list[MangaSummary] = Field(default_factory=list)


@runtime_checkable
class SourceAdapter(Protocol):
    info: SourceInfo

    async def search(self, query: str, page: int = 1) -> SourceSearchResult: ...

    async def get_manga(self, source_id: str, *, url: str | None = None) -> MangaDetail: ...

    async def get_chapter(self, source_id: str, *, url: str | None = None) -> ChapterDetail: ...

    async def latest(self) -> SourceHome: ...
