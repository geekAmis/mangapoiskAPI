from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SourceOut(BaseModel):
    code: str
    name: str
    base_url: str
    language: str = "ru"
    enabled: bool = True
    requires_cookies: bool = False
    capabilities: dict[str, bool] = Field(default_factory=dict)


class PageOut(BaseModel):
    number: int
    url: str
    width: int | None = None
    height: int | None = None


class ChapterOut(ORMModel):
    id: UUID
    manga_id: UUID
    source: str
    source_id: str
    volume: str | None = None
    number: str
    title: str = ""
    translator: str | None = None
    published_at: datetime | None = None
    page_count: int = 0
    url: str | None = None
    is_external: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ChapterDetailOut(ChapterOut):
    pages: list[PageOut] = Field(default_factory=list)
    prev_chapter_id: UUID | None = None
    next_chapter_id: UUID | None = None
    is_horizontal: bool = False


class CoverOut(BaseModel):
    """One cover variant contributed by a source title."""

    id: UUID | None = None
    source: str
    source_id: str
    url: str
    rating: float | None = None
    quality: float | None = None
    chapters_count: int = 0
    updated_at: datetime | None = None
    is_primary: bool = False


class GenreRefOut(BaseModel):
    slug: str
    label: str


class MangaOut(ORMModel):
    id: UUID
    source: str
    source_id: str
    slug: str | None = None
    title: str
    title_en: str | None = None
    title_alt: str | None = None
    description: str | None = None
    description_missing: bool = False
    description_fallback: str | None = None
    year: int | None = None
    status: str | None = None
    content_type: str | None = None
    rating: float | None = None
    rating_count: int | None = None
    poster_url: str | None = None
    adult: bool = False
    genres: list[str] = Field(default_factory=list)
    genre_slugs: list[str] = Field(default_factory=list)
    genre_details: list[GenreRefOut] = Field(default_factory=list)
    covers: list[CoverOut] = Field(default_factory=list)
    url: str | None = None
    chapters_count: int = 0
    last_chapter_at: datetime | None = None
    last_synced_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MangaDetailOut(MangaOut):
    chapters: list[ChapterOut] = Field(default_factory=list)


T = TypeVar("T")


class Paginated(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    limit: int
    has_next: bool = False


class MangaListResponse(BaseModel):
    items: list[MangaOut]
    total: int
    page: int
    limit: int
    has_next: bool


class SitemapEntryOut(BaseModel):
    """Minimal catalogue row used by the gateway sitemap collector."""

    id: UUID
    last_chapter_at: datetime | None = None
    updated_at: datetime | None = None


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


class SearchResponse(BaseModel):
    items: list[MangaOut]
    total: int
    page: int
    limit: int
    has_next: bool
    live: bool = False


class SearchSuggestionOut(BaseModel):
    """One instant-search suggestion.  It never triggers an upstream request."""

    id: UUID
    title: str
    title_en: str | None = None
    poster_url: str | None = None
    year: int | None = None
    source: str
    reason: str = "title"


class SuggestResponse(BaseModel):
    query: str = ""
    items: list[SearchSuggestionOut] = Field(default_factory=list)
    total: int = 0


class TranslatorOut(BaseModel):
    name: str
    count: int


class MangaVariantOut(BaseModel):
    id: UUID
    title: str
    source: str
    source_id: str
    poster_url: str | None = None
    rating: float | None = None
    chapters_count: int = 0
    translators: list[TranslatorOut] = Field(default_factory=list)


class MangaVariantsOut(BaseModel):
    primary_id: UUID
    items: list[MangaVariantOut] = Field(default_factory=list)


class ImportMangaRequest(BaseModel):
    source: str = Field(min_length=1, max_length=64)
    url: str | None = Field(default=None, max_length=2048)
    source_id: str | None = Field(default=None, max_length=255)
    refresh: bool = True


class ImportMangaResponse(BaseModel):
    manga: MangaDetailOut
    imported_chapters: int = 0
    imported_pages: int = 0
    source: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class UserOut(ORMModel):
    id: UUID
    email: EmailStr
    display_name: str
    role: str = "user"
    created_at: datetime | None = None


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=64)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class AuthProvidersOut(BaseModel):
    """Public feature flags for login buttons; no credentials are exposed."""

    yandex: bool = False


class YandexExchangeRequest(BaseModel):
    code: str = Field(min_length=16, max_length=256)


class YandexStatusOut(BaseModel):
    enabled: bool


class YandexCredentials(BaseModel):
    """Internal-only credentials resolved by the gateway.

    The secret uses ``repr=False`` so an accidental debug log of the model does
    not print it.  This model is never returned by a public endpoint.
    """

    client_id: str = Field(max_length=128)
    client_secret: str = Field(max_length=256, repr=False)
    redirect_uri: str = Field(max_length=512)

    @property
    def complete(self) -> bool:
        return bool(self.client_id and self.client_secret and self.redirect_uri)


class YandexStartRequest(BaseModel):
    return_url: str = Field(min_length=1, max_length=512)
    next_path: str = Field(default="/", max_length=512)
    browser_hash: str | None = Field(default=None, max_length=64)
    credentials: YandexCredentials | None = None


class YandexStartOut(BaseModel):
    authorize_url: str


class YandexCallbackRequest(BaseModel):
    state: str = Field(min_length=16, max_length=256)
    code: str = Field(min_length=1, max_length=512)
    browser_hash: str | None = Field(default=None, max_length=64)
    user_agent: str | None = Field(default=None, max_length=512)
    ip_address: str | None = Field(default=None, max_length=64)
    credentials: YandexCredentials | None = None


class YandexCallbackOut(BaseModel):
    handoff_code: str
    redirect_url: str
    expires_in: int
    is_new_user: bool = False


class YandexDenyRequest(BaseModel):
    state: str = Field(min_length=16, max_length=256)
    browser_hash: str | None = Field(default=None, max_length=64)


class YandexDenyOut(BaseModel):
    redirect_url: str


class IntegrationSecretOut(BaseModel):
    """Masked status of one encrypted integration value."""

    configured: bool = False
    hint: str = ""
    updated_at: datetime | None = None


class YandexIntegrationOut(BaseModel):
    provider: str = "yandex"
    enabled: bool = True
    configured: bool = False
    client_id: IntegrationSecretOut = Field(default_factory=IntegrationSecretOut)
    client_secret: IntegrationSecretOut = Field(default_factory=IntegrationSecretOut)
    # The redirect URI is a public callback address, not a secret.  Returning
    # it lets the admin UI prefill the exact registered value.
    redirect_uri: str | None = None
    redirect_uri_updated_at: datetime | None = None
    updated_at: datetime | None = None


class YandexIntegrationUpdate(BaseModel):
    enabled: bool | None = None
    client_id: str | None = Field(default=None, max_length=128)
    client_secret: str | None = Field(default=None, max_length=256, repr=False)
    redirect_uri: str | None = Field(default=None, max_length=512)


class YandexIntegrationTestCheck(BaseModel):
    name: str
    ok: bool
    message: str


class YandexIntegrationTestOut(BaseModel):
    ok: bool
    configured: bool
    enabled: bool
    checks: list[YandexIntegrationTestCheck] = Field(default_factory=list)
    redirect_uri: str | None = None
    message: str = ""


class YandexCredentialsOut(BaseModel):
    """Internal credential bundle.  Never exposed by a public/admin route."""

    source: Literal["db", "none"] = "none"
    enabled: bool = False
    client_id: str | None = None
    client_secret: str | None = Field(default=None, repr=False)
    redirect_uri: str | None = None
    updated_at: datetime | None = None


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=16)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=16)


class BookmarkCreate(BaseModel):
    manga_id: UUID


class BookmarkOut(ORMModel):
    id: UUID
    manga_id: UUID
    created_at: datetime
    manga: MangaOut | None = None


class ProgressUpsert(BaseModel):
    manga_id: UUID
    chapter_id: UUID
    page: int = Field(default=1, ge=1)
    total_pages: int = Field(default=0, ge=0)


class ProgressOut(ORMModel):
    manga_id: UUID
    chapter_id: UUID
    page: int
    total_pages: int
    updated_at: datetime
    manga: MangaOut | None = None
    chapter: ChapterOut | None = None


class HistoryItem(ProgressOut):
    pass


class ProgressMergeItem(BaseModel):
    """One locally stored reading position sent after sign-in.

    ``read_at`` is the client's wall-clock timestamp for the position.  The
    server keeps the newer of the local and account copies, so opening an old
    device never rewinds progress or reorders history.
    """

    manga_id: UUID
    chapter_id: UUID
    page: int = Field(default=1, ge=1)
    total_pages: int = Field(default=0, ge=0)
    read_at: datetime


class ProgressMergeRequest(BaseModel):
    items: list[ProgressMergeItem] = Field(default_factory=list, max_length=100)
    # Anonymous reading days, so a streak earned before sign-in follows the
    # account to another device instead of restarting at one day.
    read_days: list[datetime] = Field(default_factory=list, max_length=400)


class ProgressMergeOut(BaseModel):
    merged: int = 0
    unchanged: int = 0
    ignored: int = 0


class StreakOut(BaseModel):
    current: int = 0
    longest: int = 0
    read_today: bool = False
    timezone: str = "UTC"
    last_read_on: str | None = None
    days: list[str] = Field(default_factory=list)


class RecommendationListOut(BaseModel):
    items: list[MangaOut] = Field(default_factory=list)
    strategy: Literal["personalized", "popular", "related"] = "popular"


class RelatedMangaOut(BaseModel):
    series: list[MangaOut] = Field(default_factory=list)
    related: list[MangaOut] = Field(default_factory=list)


AnalyticsEventName = Literal[
    "impression",
    "click",
    "read_start",
    "read_complete",
    "finish",
]


class AnalyticsEventIn(BaseModel):
    event: AnalyticsEventName
    dedupe_key: str = Field(min_length=8, max_length=96)
    client_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    surface: str = Field(default="", max_length=32)
    manga_id: UUID | None = None
    chapter_id: UUID | None = None


class AnalyticsEventsIn(BaseModel):
    events: list[AnalyticsEventIn] = Field(default_factory=list, max_length=50)


class AnalyticsIngestOut(BaseModel):
    accepted: int = 0
    duplicates: int = 0


class AnalyticsRetentionCohort(BaseModel):
    cohort: str
    size: int = 0
    d1: int = 0
    d7: int = 0
    d30: int = 0
    d1_rate: float = 0.0
    d7_rate: float = 0.0
    d30_rate: float = 0.0


class AnalyticsRetentionOut(BaseModel):
    days: int = 30
    generated_at: datetime
    cohorts: list[AnalyticsRetentionCohort] = Field(default_factory=list)


class ReaderSettings(BaseModel):
    theme: str = "midnight"
    reader_mode: str = "vertical"  # vertical | horizontal | webtoon
    page_fit: str = "width"
    auto_scroll: bool = False
    auto_scroll_speed: int = Field(default=30, ge=5, le=200)
    show_page_numbers: bool = True
    blur_adult_posters: bool = True


class ExportJobOut(BaseModel):
    id: UUID
    status: str
    format: str
    chapter_id: UUID
    progress: int = 0
    total: int = 0
    error: str | None = None
    download_url: str | None = None
    created_at: datetime | None = None


class HealthOut(BaseModel):
    status: str
    service: str
    version: str
    checks: dict[str, Any] = Field(default_factory=dict)


class OkResponse(BaseModel):
    ok: bool = True
    message: str | None = None


TokenPair.model_rebuild()
