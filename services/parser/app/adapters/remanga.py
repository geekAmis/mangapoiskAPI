"""Remanga adapter (api.remanga.org).

Verified JSON endpoints (anonymous and signed-in, 2026-11-12):

* ``GET /api/v2/search/?query=<q>&page=<n>`` — full-text search, 20 results
  per page, ``meta`` carries ``total_items`` / ``total_pages`` / ``page``.
* ``GET /api/v2/search/catalog/?page=<n>&count=30&ordering=-rating`` —
  paginated catalogue/popular listing.  ``ordering=-id`` is the newest list.
  ``next`` is a relative API URL; the adapter reads its ``page`` parameter.
* ``GET /api/v2/titles/{dir}/`` — title detail.
* ``GET /api/v2/titles/chapters/?branch_id=<id>&page=<n>&ordering=-index`` —
  newest-first chapter list, 30 per page, integer ``next`` page.
* ``GET /api/v2/titles/chapters/{chapter_id}/`` — chapter metadata and reader
  pages (nested page groups).

Reader URLs on the site are ``/manga/{dir}/{chapter_id}``; the legacy
``/manga/{dir}/chapter/{id}`` form is accepted as an input alias.

Authentication is a bearer token.  The site stores it in the ``auth:token``
cookie; the API accepts it as ``Authorization: Bearer <token>``.  Operators can
provide either a bare token, a full Cookie header or an Authorization header
through the admin cookie store.  Without a credential the adapter behaves
anonymously and can read free chapters.

Paid/locked chapters are never bypassed.  The API returns ``is_paid: true``,
``is_bought: false`` and ``pages: []``; these chapters are skipped from the
normal chapter list (unless bought or free today) and requesting one directly
raises a typed ``chapter_paid`` error that marks it unavailable.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Any, ClassVar
from urllib.parse import parse_qs, unquote, urlparse

from manga_common.errors import (
    UpstreamError,
)
from manga_common.errors import (
    ValidationError as InputValidationError,
)
from manga_common.source_models import (
    ChapterDetail,
    ChapterSummary,
    MangaDetail,
    MangaSummary,
    Page,
    SourceCapabilities,
    SourceHome,
    SourceInfo,
    SourceSearchResult,
)
from manga_common.text import parse_float, parse_int, parse_year, strip_html

from .base import BaseAdapter
from .parsing import (
    absolute_url,
    first_text,
    normalize_number,
    parse_iso_datetime,
    path_segments,
)

_API_BASE = "https://api.remanga.org"
_SITE_BASE = "https://remanga.org"
_MANGA_PATH = "manga"
_MAX_CHAPTER_PAGES = 50
_CATALOG_PAGE_SIZE = 30
# The public API rejects ``page >= 1000`` with HTTP 422
# (``Input should be less than 1000``), even though page 999 still advertises a
# ``next`` link.  Page 999 is therefore the last valid catalogue page.
_MAX_CATALOGUE_PAGE = 999
_CATALOGUE_ORDERINGS = frozenset({"-rating", "-id", "-score", "-views", "-count_chapters"})
# The scheduler speaks a source-agnostic ``sort`` vocabulary; map it onto the
# ordering values accepted by the Remanga catalogue endpoint.
_CATALOGUE_SORT_ALIASES = {
    "popular": "-rating",
    "rating": "-rating",
    "score": "-score",
    "views": "-views",
    "newest": "-id",
    "new": "-id",
    "updated": "-id",
    "latest": "-id",
    "chapters": "-count_chapters",
}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _named(value: Any) -> str | None:
    if isinstance(value, dict):
        text = first_text(value.get("name"), value.get("label"))
        return text or None
    text = first_text(value)
    return text or None


def _cookie_pairs(raw: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for part in raw.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        if key:
            pairs[key] = value.strip()
    return pairs


def _parse_credentials(raw: str | None) -> tuple[str | None, str | None]:
    """Return ``(bearer_token, cookie_header)`` from an operator value.

    Accepted forms (case-insensitive for the prefixes):

    * ``Bearer <token>`` / ``Authorization: Bearer <token>``
    * a bare API token
    * ``auth:token=<token>`` or a complete Cookie header containing it
    * ``Cookie: ...``
    * a JSON object containing a ``cookie``/``token``/``authorization`` value
    """

    text = (raw or "").strip()
    if not text:
        return None, None
    lower = text.lower()
    cookie_prefix = lower.startswith("cookie:")
    if lower.startswith(("authorization:", "cookie:")):
        text = text.split(":", 1)[1].strip()

    lower = text.lower()
    if lower.startswith("bearer "):
        token = text[7:].strip().strip('"')
        return token or None, None

    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            for key in ("cookie", "token", "authorization", "value"):
                candidate = payload.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    return _parse_credentials(candidate)

    pairs = _cookie_pairs(text)
    token = pairs.get("auth:token") or pairs.get("auth:server-token")
    if token:
        token = unquote(token).strip().strip('"')
        return token or None, None

    # A complete Cookie header without an auth token is still useful for the
    # site's DDoS-Guard cookies; send it as a Cookie header.
    if ";" in text or cookie_prefix or "=" in text:
        return None, text

    token = text.split()[0].strip().strip('"')
    return token or None, None


@dataclass(frozen=True, slots=True, repr=False)
class _RemangaCredentials:
    token: str | None = None
    cookie_header: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.token or self.cookie_header)

    @property
    def mode(self) -> str:
        if self.token:
            return "bearer"
        if self.cookie_header:
            return "cookie"
        return "anonymous"

    @property
    def fingerprint(self) -> str:
        seed = self.token or self.cookie_header or ""
        if not seed:
            return "anonymous"
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


class RemangaAdapter(BaseAdapter):
    """Adapter for ``remanga.org``."""

    info = SourceInfo(
        code="remanga",
        name="Remanga",
        base_url=_SITE_BASE,
        language="ru",
        enabled=True,
        requires_cookies=True,
        capabilities=SourceCapabilities(
            search=True,
            catalog=True,
            manga=True,
            chapters=True,
            pages=True,
            latest=True,
            requires_auth_for_pages=False,
        ),
        notes=(
            "Public JSON API verified for search, catalogue/popular pages, title "
            "details, chapter lists and reader pages. Cover URLs use "
            "remanga.org/media; page images use img3.reimg2.org (no Referer) and "
            "img-reserve.reimg2.org (Referer: https://remanga.org/). An optional "
            "operator credential is sent as Authorization: Bearer; paid/locked "
            "chapters are skipped and never bypassed."
        ),
    )
    allowed_hosts = frozenset({"remanga.org", "www.remanga.org", "api.remanga.org"})
    max_concurrency = 1
    max_catalogue_pages = _MAX_CATALOGUE_PAGE
    default_headers: ClassVar[dict[str, str]] = {
        "Accept": "application/json, text/plain, */*",
        "Origin": _SITE_BASE,
        "Referer": f"{_SITE_BASE}/",
        "X-Client-Name": "web",
    }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._credentials = _RemangaCredentials()
        self.set_cookie(self._cookie)

    def _configured_cookie(self, settings) -> str | None:  # type: ignore[no-untyped-def]
        return (settings.remanga_cookie or "").strip() or None

    # ------------------------------------------------------------------
    # Credentials
    # ------------------------------------------------------------------

    def set_cookie(self, value: str | None) -> None:
        """Update the upstream credential in-place (admin cookie endpoint)."""

        token, cookie_header = _parse_credentials(value)
        self._cookie = (value or "").strip() or None
        self._credentials = _RemangaCredentials(token=token, cookie_header=cookie_header)

    @property
    def cookie_configured(self) -> bool:
        return self._credentials.configured

    @property
    def cookie_mode(self) -> str:
        return self._credentials.mode

    def _request_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = super()._request_headers(extra)
        # BaseAdapter adds the raw operator value as Cookie; this adapter
        # converts it to the API's bearer auth and only sends a Cookie header
        # when the value does not contain a usable token.
        headers.pop("Cookie", None)
        if self._credentials.cookie_header:
            headers["Cookie"] = self._credentials.cookie_header
        if self._credentials.token:
            headers["Authorization"] = f"Bearer {self._credentials.token}"
        return headers

    # ------------------------------------------------------------------
    # Mapping
    # ------------------------------------------------------------------

    def _cover_url(self, item: dict[str, Any]) -> str | None:
        cover = item.get("cover")
        if isinstance(cover, str):
            return absolute_url(_SITE_BASE, cover)
        cover_dict = _as_dict(cover)
        return absolute_url(
            _SITE_BASE,
            first_text(cover_dict.get("mid"), cover_dict.get("high"), cover_dict.get("low")),
        )

    @staticmethod
    def _genres(item: dict[str, Any]) -> list[str]:
        names: list[str] = []
        for key in ("genres", "categories"):
            for genre in _as_list(item.get(key)):
                name = _named(genre)
                if name and name not in names:
                    names.append(name)
        return names

    @staticmethod
    def _publisher_names(*values: Any) -> list[str]:
        names: list[str] = []
        for value in values:
            for publisher in _as_list(value):
                if isinstance(publisher, dict):
                    name = first_text(publisher.get("name"))
                    if name and name not in names:
                        names.append(name)
        return names

    def _summary_from_search(self, item: Any) -> MangaSummary | None:
        if not isinstance(item, dict):
            return None
        directory = first_text(item.get("dir"))
        numeric_id = parse_int(item.get("id"))
        source_id = directory or (str(numeric_id) if numeric_id is not None else "")
        if not source_id:
            return None
        return MangaSummary(
            source=self.info.code,
            source_id=source_id,
            slug=directory or None,
            title=first_text(item.get("main_name"), item.get("secondary_name"), source_id),
            title_en=first_text(item.get("secondary_name")) or None,
            title_alt=first_text(item.get("another_name")) or None,
            year=parse_year(item.get("issue_year")),
            status=_named(item.get("translate_status")) or _named(item.get("status")),
            content_type=_named(item.get("type")),
            rating=parse_float(item.get("avg_rating")),
            rating_count=parse_int(item.get("total_votes")),
            poster_url=self._cover_url(item),
            adult=bool(item.get("is_erotic")),
            genres=self._genres(item),
            updated_at=parse_iso_datetime(item.get("uploaded")),
            chapters_count=parse_int(item.get("count_chapters")),
            url=absolute_url(_SITE_BASE, f"/manga/{directory}") if directory else None,
        )

    def _summary_from_detail(self, title: dict[str, Any]) -> MangaSummary:
        directory = first_text(title.get("dir"))
        age_label = first_text(_as_dict(title.get("age_limit")).get("name"))
        return MangaSummary(
            source=self.info.code,
            source_id=directory or first_text(title.get("id")),
            slug=directory or None,
            title=first_text(title.get("main_name"), title.get("secondary_name"), directory),
            title_en=first_text(title.get("secondary_name")) or None,
            title_alt=first_text(title.get("another_name")) or None,
            description=strip_html(title.get("description")) or None,
            year=parse_year(title.get("issue_year")),
            status=_named(title.get("translate_status")) or _named(title.get("status")),
            content_type=_named(title.get("type")),
            rating=parse_float(title.get("avg_rating")),
            rating_count=parse_int(title.get("total_votes")),
            poster_url=self._cover_url(title),
            adult=bool(title.get("is_erotic")) or "18+" in age_label,
            genres=self._genres(title),
            updated_at=parse_iso_datetime(title.get("uploaded")),
            chapters_count=parse_int(title.get("count_chapters")),
            url=absolute_url(_SITE_BASE, f"/manga/{directory}") if directory else None,
        )

    @staticmethod
    def _chapter_access(item: dict[str, Any]) -> str:
        """Classify a chapter row without ever fetching paid pages."""

        if item.get("is_published") is False:
            return "unpublished"
        if item.get("is_bought"):
            return "purchased"
        if not item.get("is_paid"):
            return "free"
        if item.get("is_free_today"):
            return "free_today"
        return "locked"

    @classmethod
    def _chapter_available(cls, item: dict[str, Any]) -> bool:
        return cls._chapter_access(item) not in {"locked", "unpublished"}

    def _chapter_summary(
        self,
        directory: str | None,
        item: Any,
        *,
        translator: str | None = None,
    ) -> ChapterSummary | None:
        if not isinstance(item, dict):
            return None
        chapter_id = parse_int(item.get("id"))
        if chapter_id is None:
            return None
        if item.get("is_published") is False:
            return None
        number = normalize_number(item.get("chapter")) or "0"
        volume = normalize_number(item.get("tome")) or None
        publishers = self._publisher_names(item.get("publishers"))
        url = self._chapter_url(directory, chapter_id)
        return ChapterSummary(
            source=self.info.code,
            source_id=str(chapter_id),
            manga_source_id=directory or "",
            volume=volume,
            number=number,
            title=first_text(item.get("name"), f"Глава {number}"),
            translator=translator or (publishers[0] if publishers else None),
            published_at=(
                parse_iso_datetime(item.get("upload_date"))
                or parse_iso_datetime(item.get("pub_date"))
                or parse_iso_datetime(item.get("delay_pub_date"))
            ),
            page_count=0,
            url=url,
            is_external=False,
        )

    @staticmethod
    def _chapter_url(directory: str | None, chapter_id: int) -> str | None:
        if not directory:
            return None
        return f"{_SITE_BASE}/manga/{directory}/{chapter_id}"

    # ------------------------------------------------------------------
    # Upstream helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _next_page(value: Any) -> int | None:
        """Read the integer ``next`` field, also tolerating a full page URL."""

        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        text = str(value).strip()
        if not text:
            return None
        if text.isdigit():
            return int(text)
        parsed = urlparse(text)
        candidate = (parse_qs(parsed.query).get("page") or [None])[0]
        return parse_int(candidate)

    @staticmethod
    def _is_catalogue_page_limit_error(exc: UpstreamError) -> bool:
        """True when the upstream rejected ``page`` because it is past the cap.

        Remanga answers ``page=1000`` with
        ``{"detail":[{"loc":["page"],"msg":"Input should be less than 1000",
        "type":"less_than"}]}``.  Only that exact field/validator combination is
        an end-of-catalogue signal; a malformed ordering, a bad ``count`` or a
        genuine ``page=1`` validation error must still surface as a failure.
        """

        details = exc.details
        if not isinstance(details, dict) or details.get("status_code") not in (422, "422"):
            return False
        body = details.get("body")
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except ValueError:
                return False
        if not isinstance(body, dict):
            return False
        detail = body.get("detail")
        if not isinstance(detail, list):
            return False
        for entry in detail:
            if not isinstance(entry, dict):
                continue
            loc = entry.get("loc")
            if not isinstance(loc, (list, tuple)) or list(loc) != ["page"]:
                continue
            if entry.get("type") == "less_than":
                return True
        return False

    async def _fetch_chapters(
        self,
        branch_id: int,
        directory: str | None,
        limit: int,
        *,
        translator: str | None = None,
        include_locked: bool = False,
    ) -> list[ChapterSummary]:
        if limit <= 0:
            return []
        chapters: list[ChapterSummary] = []
        seen: set[int] = set()
        page = 1
        for _ in range(_MAX_CHAPTER_PAGES):
            payload = await self.request_json(
                f"{_API_BASE}/api/v2/titles/chapters/",
                params={
                    "branch_id": branch_id,
                    "page": page,
                    "ordering": "-index",
                    "user_data": 1,
                },
            )
            if not isinstance(payload, dict):
                raise UpstreamError(
                    "Remanga: chapter list returned an unexpected payload",
                    code="invalid_upstream_payload",
                    details={"source": self.info.code},
                )
            rows = [item for item in _as_list(payload.get("results")) if isinstance(item, dict)]
            if not rows:
                break
            for item in rows:
                chapter_id = parse_int(item.get("id"))
                if chapter_id is not None and chapter_id in seen:
                    continue
                if chapter_id is not None:
                    seen.add(chapter_id)
                if not include_locked and not self._chapter_available(item):
                    continue
                chapter = self._chapter_summary(directory, item, translator=translator)
                if chapter is None:
                    continue
                chapters.append(chapter)
                if len(chapters) >= limit:
                    return chapters[:limit]
            next_page = self._next_page(payload.get("next"))
            if next_page is None or next_page <= page:
                break
            page = next_page
        return chapters[:limit]

    @staticmethod
    def _pages(raw_pages: Any) -> list[Page]:
        entries: list[dict[str, Any]] = []
        for group in _as_list(raw_pages):
            if isinstance(group, list):
                entries.extend(item for item in group if isinstance(item, dict))
            elif isinstance(group, dict):
                entries.append(group)
        pages: list[Page] = []
        for entry in entries:
            url = absolute_url(_SITE_BASE, first_text(entry.get("link")))
            if not url:
                continue
            pages.append(
                Page(
                    number=len(pages) + 1,
                    url=url,
                    width=parse_int(entry.get("width")),
                    height=parse_int(entry.get("height")),
                )
            )
        return pages

    async def _catalogue_items(
        self,
        page: int,
        ordering: str,
    ) -> tuple[list[MangaSummary], bool]:
        if self.max_catalogue_pages is not None and page > self.max_catalogue_pages:
            # Past the hard upstream cap there is nothing left to fetch.  This
            # also recovers a persisted cursor that was already stuck at 1000.
            return [], False
        try:
            payload = await self.request_json(
                f"{_API_BASE}/api/v2/search/catalog/",
                params={
                    "page": page,
                    "count": _CATALOG_PAGE_SIZE,
                    "ordering": ordering,
                    "unstrict_search_fields": "categories",
                },
            )
        except UpstreamError as exc:
            if self._is_catalogue_page_limit_error(exc):
                return [], False
            raise
        if not isinstance(payload, dict):
            raise UpstreamError(
                "Remanga: catalogue returned an unexpected payload",
                code="invalid_upstream_payload",
                details={"source": self.info.code},
            )
        items = [
            summary
            for summary in (
                self._summary_from_search(item) for item in _as_list(payload.get("results"))
            )
            if summary is not None
        ]
        next_page = self._next_page(payload.get("next"))
        has_next = next_page is not None and (
            self.max_catalogue_pages is None or next_page <= self.max_catalogue_pages
        )
        return items, has_next

    # ------------------------------------------------------------------
    # Public adapter API
    # ------------------------------------------------------------------

    async def search(self, query: str, page: int = 1) -> SourceSearchResult:
        query = self.normalise_query(query)
        if page < 1:
            raise InputValidationError("page must be >= 1", code="invalid_page")
        cached = await self.cache_read_model("search", (query, page), SourceSearchResult)
        if cached is not None:
            return cached

        payload = await self.request_json(
            f"{_API_BASE}/api/v2/search/",
            params={"query": query, "page": page},
        )
        if not isinstance(payload, dict):
            raise UpstreamError(
                "Remanga: search returned an unexpected payload",
                code="invalid_upstream_payload",
                details={"source": self.info.code},
            )
        items = [
            summary
            for summary in (
                self._summary_from_search(item) for item in _as_list(payload.get("results"))
            )
            if summary is not None
        ]
        meta = _as_dict(payload.get("meta"))
        total_pages = parse_int(meta.get("total_pages")) or 0
        result = SourceSearchResult(
            source=self.info.code,
            items=items,
            page=parse_int(meta.get("page")) or page,
            total=parse_int(meta.get("total_items")),
            has_next=page < total_pages,
            total_pages=total_pages or None,
            per_page=20,
        )
        await self.cache_write_model("search", (query, page), result)
        return result

    async def catalogue(
        self,
        page: int = 1,
        *,
        sort: str = "popular",
        ordering: str | None = None,
    ) -> SourceSearchResult:
        """Return one page of the catalogue/popular listing.

        ``sort`` is the source-agnostic scheduler vocabulary; ``ordering`` is
        the native Remanga value and takes precedence when both are supplied.
        """

        chosen = ordering or _CATALOGUE_SORT_ALIASES.get(sort.strip().lower(), sort)
        if page < 1:
            raise InputValidationError("page must be >= 1", code="invalid_page")
        if chosen not in _CATALOGUE_ORDERINGS:
            raise InputValidationError(
                f"Unsupported catalogue ordering '{chosen}'",
                code="invalid_ordering",
                details={"allowed": sorted(_CATALOGUE_ORDERINGS)},
            )
        cached = await self.cache_read_model("catalogue", (page, chosen), SourceSearchResult)
        if cached is not None:
            return cached
        items, has_next = await self._catalogue_items(page, chosen)
        result = SourceSearchResult(
            source=self.info.code,
            items=items,
            page=page,
            total=None,
            has_next=has_next,
            per_page=_CATALOG_PAGE_SIZE,
        )
        await self.cache_write_model("catalogue", (page, chosen), result)
        return result

    async def popular(self, page: int = 1) -> SourceSearchResult:
        return await self.catalogue(page, ordering="-rating")

    async def newest(self, page: int = 1) -> SourceSearchResult:
        return await self.catalogue(page, ordering="-id")

    async def get_manga(
        self,
        source_id: str = "",
        *,
        url: str | None = None,
        chapters_limit: int = 100,
    ) -> MangaDetail:
        directory = self._resolve_manga(source_id, url)
        limit = self.clamp_chapters_limit(chapters_limit)
        cache_parts = (directory, limit, self._credentials.fingerprint)
        cached = await self.cache_read_model("manga", cache_parts, MangaDetail)
        if cached is not None:
            return cached

        payload = await self.request_json(f"{_API_BASE}/api/v2/titles/{directory}/")
        if not isinstance(payload, dict):
            raise UpstreamError(
                "Remanga: title returned an unexpected payload",
                code="invalid_upstream_payload",
                details={"source": self.info.code},
            )
        directory = first_text(payload.get("dir")) or directory
        branches = [branch for branch in _as_list(payload.get("branches")) if isinstance(branch, dict)]
        branch_id: int | None = None
        translator: str | None = None
        if branches:
            # The API can expose several translation branches.  The primary
            # list is the one with the most chapters; ties keep the lowest id.
            best = max(
                branches,
                key=lambda branch: (
                    parse_int(branch.get("count_chapters")) or 0,
                    -(parse_int(branch.get("id")) or 0),
                ),
            )
            branch_id = parse_int(best.get("id"))
            publisher_names = self._publisher_names(best.get("publishers"))
            translator = publisher_names[0] if publisher_names else None
        chapters = (
            await self._fetch_chapters(
                branch_id,
                directory,
                limit,
                translator=translator,
            )
            if branch_id is not None and limit
            else []
        )
        latest_chapter = chapters[0] if chapters else None
        summary = self._summary_from_detail(payload)
        if latest_chapter is not None:
            summary = summary.model_copy(update={"latest_chapter": latest_chapter})
        result = MangaDetail(**summary.model_dump(), chapters=chapters)
        await self.cache_write_model("manga", cache_parts, result)
        return result

    async def get_chapter(
        self,
        source_id: str = "",
        *,
        url: str | None = None,
    ) -> ChapterDetail:
        directory, chapter_id = self._resolve_chapter(source_id, url)
        cache_parts = (directory or "", chapter_id, self._credentials.fingerprint)
        cached = await self.cache_read_model("chapter", cache_parts, ChapterDetail)
        if cached is not None:
            return cached

        payload = await self.request_json(f"{_API_BASE}/api/v2/titles/chapters/{chapter_id}/")
        if not isinstance(payload, dict):
            raise UpstreamError(
                "Remanga: chapter returned an unexpected payload",
                code="invalid_upstream_payload",
                details={"source": self.info.code},
            )

        if payload.get("is_published") is False:
            raise UpstreamError(
                "Remanga: chapter is not published",
                code="chapter_unpublished",
                details={
                    "source": self.info.code,
                    "chapter_id": chapter_id,
                    "available": False,
                    "reason": "unpublished",
                },
            )

        access = self._chapter_access(payload)
        if access in {"locked", "unpublished"}:
            raise UpstreamError(
                "Remanga: chapter is paid or locked and cannot be read",
                code="chapter_paid",
                details={
                    "source": self.info.code,
                    "chapter_id": chapter_id,
                    "title_id": parse_int(payload.get("title_id")),
                    "price": first_text(payload.get("price")) or None,
                    "is_paid": bool(payload.get("is_paid")),
                    "is_bought": bool(payload.get("is_bought")),
                    "is_free_today": bool(payload.get("is_free_today")),
                    "available": False,
                    "reason": "paid_locked" if access == "locked" else "unpublished",
                },
            )

        pages = self._pages(payload.get("pages"))
        if not pages:
            raise UpstreamError(
                "Remanga: chapter has no page images",
                code="pages_unavailable",
                details={
                    "source": self.info.code,
                    "chapter_id": chapter_id,
                    "title_id": parse_int(payload.get("title_id")),
                    "is_paid": bool(payload.get("is_paid")),
                    "is_bought": bool(payload.get("is_bought")),
                    "is_free_today": bool(payload.get("is_free_today")),
                    "available": False,
                    "reason": "empty_pages",
                },
            )

        number = normalize_number(payload.get("chapter")) or "0"
        volume = normalize_number(payload.get("tome")) or None
        publishers = self._publisher_names(payload.get("publishers"))
        chapter_url = self._chapter_url(directory, chapter_id) or url
        chapter = ChapterSummary(
            source=self.info.code,
            source_id=str(chapter_id),
            manga_source_id=directory or "",
            volume=volume,
            number=number,
            title=first_text(payload.get("name"), f"Глава {number}"),
            translator=publishers[0] if publishers else None,
            published_at=(
                parse_iso_datetime(payload.get("upload_date"))
                or parse_iso_datetime(payload.get("pub_date"))
                or parse_iso_datetime(payload.get("delay_pub_date"))
            ),
            page_count=len(pages),
            url=chapter_url,
            is_external=False,
        )

        def neighbour_url(value: Any) -> str | None:
            neighbour = _as_dict(value)
            neighbour_id = parse_int(neighbour.get("id"))
            if neighbour_id is None or not directory:
                return None
            return self._chapter_url(directory, neighbour_id)

        detail = ChapterDetail(
            chapter=chapter,
            pages=pages,
            prev_url=neighbour_url(payload.get("previous")),
            next_url=neighbour_url(payload.get("next")),
            is_horizontal=False,
        )
        await self.cache_write_model("chapter", cache_parts, detail)
        return detail

    async def latest(self) -> SourceHome:
        cached = await self.cache_read_model("home", (), SourceHome)
        if cached is not None:
            return cached

        popular_result, newest_result = await asyncio.gather(
            self.catalogue(1, ordering="-rating"),
            self.catalogue(1, ordering="-id"),
            return_exceptions=True,
        )
        popular: list[MangaSummary] = []
        latest: list[MangaSummary] = []
        errors: list[BaseException] = []
        if isinstance(popular_result, BaseException):
            errors.append(popular_result)
        else:
            popular = popular_result.items
        if isinstance(newest_result, BaseException):
            errors.append(newest_result)
        else:
            latest = newest_result.items
        if not popular and not latest:
            if errors:
                raise errors[0]
            raise UpstreamError(
                "Remanga: catalogue returned no titles",
                code="invalid_upstream_payload",
                details={"source": self.info.code},
            )
        home = SourceHome(source=self.info.code, popular=popular, latest=latest)
        await self.cache_write_model("home", (), home)
        return home

    # ------------------------------------------------------------------
    # Identifier resolution
    # ------------------------------------------------------------------

    def _resolve_manga(self, source_id: str, url: str | None) -> str:
        if url:
            self.assert_allowed_url(url)
            return self._manga_from_url(url)
        value = (source_id or "").strip()
        if value.startswith(("http://", "https://")):
            self.assert_allowed_url(value)
            return self._manga_from_url(value)
        value = value.strip("/")
        for _ in range(2):
            if value.startswith(f"{_MANGA_PATH}/"):
                value = value[len(_MANGA_PATH) + 1 :]
            elif value.startswith("ru/"):
                value = value[3:]
            else:
                break
        if "?" in value:
            value = value.split("?", 1)[0]
        if "/" in value:
            value = value.split("/", 1)[0]
        if not value:
            raise InputValidationError(
                "Remanga: source_id or url is required",
                code="missing_source_id",
            )
        if value.isdigit():
            raise InputValidationError(
                "Remanga: titles are addressed by dir/slug, not numeric id",
                code="invalid_source_id",
                details={"source": self.info.code, "source_id": source_id or None},
            )
        return value

    def _manga_from_url(self, raw_url: str) -> str:
        segments = path_segments(raw_url)
        for marker in (_MANGA_PATH, "titles"):
            if marker in segments:
                index = segments.index(marker)
                if index + 1 < len(segments):
                    candidate = segments[index + 1]
                    if candidate not in {"chapters"}:
                        return candidate
        raise InputValidationError(
            "Remanga: URL must point to /manga/<dir>",
            code="invalid_source_url",
        )

    def _resolve_chapter(self, source_id: str, url: str | None) -> tuple[str | None, int]:
        if url:
            self.assert_allowed_url(url)
            return self._chapter_from_url(url)
        value = (source_id or "").strip()
        if value.startswith(("http://", "https://")):
            self.assert_allowed_url(value)
            return self._chapter_from_url(value)
        parts = [part for part in value.strip("/").split("/") if part]
        while parts and parts[0] in {_MANGA_PATH, "ru"}:
            parts = parts[1:]
        if "chapters" in parts:
            index = parts.index("chapters")
            chapter_id = parse_int(parts[index + 1]) if index + 1 < len(parts) else None
            if chapter_id is None:
                raise InputValidationError(
                    "Remanga: chapter URL does not contain a numeric id",
                    code="invalid_source_id",
                )
            return None, chapter_id
        if not parts:
            raise InputValidationError(
                "Remanga: source_id or url is required",
                code="missing_source_id",
            )
        chapter_id = parse_int(parts[-1])
        if chapter_id is None:
            raise InputValidationError(
                "Remanga: source_id must be a numeric chapter id or a full chapter URL",
                code="invalid_source_id",
            )
        directory = parts[0] if len(parts) >= 2 and parts[0] != "chapter" else None
        return directory, chapter_id

    def _chapter_from_url(self, raw_url: str) -> tuple[str | None, int]:
        segments = path_segments(raw_url)
        if "chapters" in segments and "titles" in segments:
            index = segments.index("chapters")
            chapter_id = parse_int(segments[index + 1]) if index + 1 < len(segments) else None
            if chapter_id is not None:
                return None, chapter_id
        if _MANGA_PATH in segments:
            index = segments.index(_MANGA_PATH)
            if index + 2 < len(segments):
                directory = segments[index + 1]
                offset = 3 if segments[index + 2] == "chapter" else 2
                if index + offset < len(segments):
                    chapter_id = parse_int(segments[index + offset])
                    if chapter_id is not None:
                        return directory, chapter_id
            raise InputValidationError(
                "Remanga: URL must point to /manga/<dir>/<chapter_id>",
                code="invalid_source_url",
            )
        raise InputValidationError(
            "Remanga: URL must point to /manga/<dir>/<chapter_id>",
            code="invalid_source_url",
        )
