"""MangaLib adapter (api.imglib.info, with api.lib.social as an alias).

Search, catalogue, manga detail, chapter lists and reader pages are verified
against the public JSON API.  The detail endpoint works when ``Site-Id: 1`` is
sent; without that header it returns 404, so the adapter keeps a search-result
fallback for resilience.

Reader pages come from
``GET /api/manga/{slug_url}/chapter?volume={volume}&number={number}``.  The
response contains protocol-relative image paths such as
``//manga/{slug}/chapters/{chapter_id}/{image}``.  Browser HARs show the
``compress`` server at ``https://img3.cdnlibs.org``; the adapter normalises to
that host.  ``img2.imglib.info`` is the ``main`` server but returns 403 unless a
``Referer: https://mangalib.me/`` header accompanies the image request.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar
from urllib.parse import urlparse

from manga_common.errors import (
    NotFoundError,
    UpstreamError,
)
from manga_common.errors import (
    TimeoutError as UpstreamTimeoutError,
)
from manga_common.errors import (
    ValidationError as InputValidationError,
)
from manga_common.logging import log_event
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

_API_BASE = "https://api.imglib.info"
_SITE_BASE = "https://mangalib.me"
_IMAGE_BASE = "https://img3.cdnlibs.org"
_MANGA_PATH = "manga"
_VOLUME_SEGMENT_RE = re.compile(r"^v(?P<value>\d+(?:\.\d+)?)$", re.IGNORECASE)
_NUMBER_SEGMENT_RE = re.compile(r"^c(?P<value>\d+(?:\.\d+)?)$", re.IGNORECASE)
_NUMERIC_SEGMENT_RE = re.compile(r"^\d+(?:\.\d+)?$")

# Upstream accepts a whitelist of expansion fields.  Requesting the detail
# fields explicitly is what makes description/genres available at all.
_DETAIL_FIELDS: tuple[str, ...] = (
    "summary",
    "genres",
    "tags",
    "authors",
    "artists",
    "publisher",
    "chap_count",
    "status_id",
    "manga_status_id",
    "extra_release_status",
    "format",
    "releaseDate",
    "country",
    "rate_avg",
    "views",
    "otherNames",
)

_CATALOGUE_SORTS: dict[str, str] = {
    "popular": "views",
    "updated": "last_chapter_at",
    "new": "created_at",
    "rating": "rate_avg",
    "title": "name",
    "chapters": "chap_count",
}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _label(value: Any) -> str | None:
    if isinstance(value, dict):
        label = first_text(value.get("label"), value.get("name"))
        return label or None
    text = first_text(value)
    return text or None


def _rich_text(value: Any) -> str:
    """Flatten MangaLib's ProseMirror document (``{"type": "doc", ...}``)."""

    if isinstance(value, str):
        return strip_html(value)
    if not isinstance(value, dict):
        return ""
    parts: list[str] = []
    node_type = str(value.get("type") or "")
    text = value.get("text")
    if isinstance(text, str) and text:
        parts.append(text)
    for child in _as_list(value.get("content")):
        rendered = _rich_text(child)
        if rendered:
            parts.append(rendered)
    joined = " ".join(parts).strip()
    if node_type in {"paragraph", "blockquote", "list_item"} and joined:
        return joined + "\n"
    return joined


class MangaLibAdapter(BaseAdapter):
    """Best-effort adapter for ``mangalib.me``."""

    info = SourceInfo(
        code="mangalib",
        name="MangaLib",
        base_url=_SITE_BASE,
        language="ru",
        enabled=True,
        requires_cookies=False,
        capabilities=SourceCapabilities(
            search=True,
            catalog=True,
            manga=True,
            chapters=True,
            pages=True,
            latest=True,
        ),
        notes=(
            "Public API supports search/catalogue/detail/chapters and reader pages. "
            "Detail requires Site-Id; page images use img3.cdnlibs.org."
        ),
    )
    allowed_hosts = frozenset(
        {
            "mangalib.me",
            "www.mangalib.me",
            "api.lib.social",
            "api.imglib.info",
        }
    )
    max_concurrency = 2
    default_headers: ClassVar[dict[str, str]] = {
        "Accept": "application/json",
        "Origin": _SITE_BASE,
        "Referer": f"{_SITE_BASE}/",
        "Site-Id": "1",
        "Client-Time-Zone": "Europe/Moscow",
    }

    def __init__(self, client, settings, cache) -> None:  # type: ignore[no-untyped-def]
        super().__init__(client, settings, cache)
        self._detail_unavailable = False

    def _configured_cookie(self, settings) -> str | None:  # type: ignore[no-untyped-def]
        return (settings.mangalib_cookie or "").strip() or None

    # ------------------------------------------------------------------
    # Mapping
    # ------------------------------------------------------------------

    def _summary_from_item(self, item: Any) -> MangaSummary | None:
        if not isinstance(item, dict):
            return None
        slug = first_text(item.get("slug"))
        slug_url = first_text(item.get("slug_url"))
        numeric_id = parse_int(item.get("id"))
        if not slug_url and numeric_id is not None and slug:
            slug_url = f"{numeric_id}--{slug}"
        source_id = slug_url or slug
        if not source_id:
            return None
        title = first_text(item.get("rus_name"), item.get("name"), item.get("eng_name"), slug)
        cover = _as_dict(item.get("cover"))
        rating = _as_dict(item.get("rating"))
        age_label = first_text(_as_dict(item.get("ageRestriction")).get("label"))
        genres = [
            first_text(genre.get("name"), genre.get("label"))
            for genre in _as_list(item.get("genres"))
            if isinstance(genre, dict)
        ]
        description = strip_html(_rich_text(item.get("summary"))) or strip_html(
            item.get("description")
        )
        return MangaSummary(
            source=self.info.code,
            source_id=source_id,
            slug=slug or (slug_url.split("--", 1)[-1] if slug_url else None),
            title=title,
            title_en=first_text(item.get("eng_name")) or None,
            title_alt=first_text(item.get("name")) if first_text(item.get("name")) != title else None,
            description=description or None,
            year=parse_year(item.get("releaseDateString") or item.get("releaseDate")),
            status=_label(item.get("status")),
            content_type=_label(item.get("type")),
            rating=parse_float(rating.get("average")),
            rating_count=parse_int(rating.get("votes")),
            poster_url=absolute_url(
                _SITE_BASE,
                first_text(cover.get("default"), cover.get("md"), cover.get("thumbnail")),
            ),
            adult=age_label == "18+" or "18+" in age_label,
            genres=[genre for genre in genres if genre],
            url=f"{_SITE_BASE}/ru/manga/{source_id}",
            updated_at=parse_iso_datetime(item.get("last_chapter_at")),
            chapters_count=parse_int(item.get("chap_count") or item.get("items_count")),
        )

    def _chapter_summary(self, manga_slug_url: str, item: Any) -> ChapterSummary | None:
        if not isinstance(item, dict):
            return None
        chapter_id = parse_int(item.get("id"))
        volume = normalize_number(item.get("volume")) or None
        number = normalize_number(item.get("number"))
        if not number:
            return None
        branches = [branch for branch in _as_list(item.get("branches")) if isinstance(branch, dict)]
        branch_id = parse_int(branches[0].get("id")) if branches else chapter_id
        translator = None
        if branches:
            teams = [team for team in _as_list(branches[0].get("teams")) if isinstance(team, dict)]
            if teams:
                translator = first_text(teams[0].get("name")) or None
        published_at = (
            parse_iso_datetime(branches[0].get("created_at")) if branches else None
        ) or parse_iso_datetime(item.get("created_at"))
        source_id = str(chapter_id) if chapter_id is not None else f"{volume or '1'}-{number}"
        url = f"{_SITE_BASE}/ru/manga/{manga_slug_url}/read/v{volume or '1'}/c{number}"
        if branch_id is not None:
            url = f"{url}?bid={branch_id}"
        return ChapterSummary(
            source=self.info.code,
            source_id=source_id,
            manga_source_id=manga_slug_url,
            volume=volume,
            number=number,
            title=first_text(item.get("name"), f"Глава {number}"),
            translator=translator,
            published_at=published_at,
            page_count=0,
            url=url,
            is_external=False,
        )

    # ------------------------------------------------------------------
    # Upstream helpers
    # ------------------------------------------------------------------

    async def _catalogue(self, *, sort_by: str | None = None) -> list[MangaSummary]:
        params: dict[str, Any] = {
            "q": "",
            "site_id[]": "1",
            "page": 1,
            "limit": 20,
        }
        if sort_by:
            params["sort_by"] = sort_by
        payload = await self.request_json(f"{_API_BASE}/api/manga", params=params)
        if not isinstance(payload, dict):
            raise UpstreamError(
                "MangaLib: catalogue returned an unexpected payload",
                code="invalid_upstream_payload",
                details={"source": self.info.code},
            )
        return [
            summary
            for summary in (
                self._summary_from_item(item) for item in _as_list(payload.get("data"))
            )
            if summary is not None
        ]

    async def _try_detail(self, slug_url: str, slug: str) -> dict[str, Any] | None:
        if self._detail_unavailable:
            return None
        variants: list[str] = []
        if slug_url:
            variants.append(slug_url)
        if slug and slug != slug_url:
            variants.append(slug)
        for identifier in variants:
            try:
                payload = await self.request_json(
                    f"{_API_BASE}/api/manga/{identifier}",
                    params={"site_id[]": "1", "fields[]": list(_DETAIL_FIELDS)},
                )
            except NotFoundError:
                continue
            data = _as_dict(payload.get("data")) if isinstance(payload, dict) else {}
            if data:
                return data
            if isinstance(payload, dict) and payload.get("id") is not None:
                return payload
        self._detail_unavailable = True
        log_event(
            self._logger,
            "mangalib_detail_unavailable",
            source=self.info.code,
            slug_url=slug_url,
        )
        return None

    async def _fetch_chapters(self, slug_url: str) -> list[ChapterSummary]:
        payload = await self.request_json(f"{_API_BASE}/api/manga/{slug_url}/chapters")
        if not isinstance(payload, dict):
            raise UpstreamError(
                "MangaLib: chapter list returned an unexpected payload",
                code="invalid_upstream_payload",
                details={"source": self.info.code},
            )
        chapters: list[ChapterSummary] = []
        for item in _as_list(payload.get("data")):
            chapter = self._chapter_summary(slug_url, item)
            if chapter is not None:
                chapters.append(chapter)
        return chapters

    @staticmethod
    def _page_url(value: str) -> str | None:
        """Normalise an upstream page path to the working image host."""

        text = (value or "").strip()
        if not text:
            return None
        if text.startswith(("http://", "https://")):
            parsed = urlparse(text)
            if parsed.netloc.lower() in {
                "img2.imglib.info",
                "img3.imglib.info",
                "img3.cdnlibs.org",
            }:
                path = parsed.path.lstrip("/")
                if path:
                    suffix = f"?{parsed.query}" if parsed.query else ""
                    return f"{_IMAGE_BASE}/{path}{suffix}"
            return text
        path = text.lstrip("/")
        if not path:
            return None
        # img3 is the HAR-observed "compress" server; img2 ("main") needs a
        # Referer header and is prone to 403s in server-to-server fetching.
        return f"{_IMAGE_BASE}/{path}"

    def _reader_pages(self, slug_url: str, data: dict[str, Any]) -> list[Page]:
        manga_slug = slug_url.split("--", 1)[-1] if "--" in slug_url else slug_url
        chapter_slug = first_text(data.get("slug"), data.get("id"))
        pages: list[Page] = []
        for raw in _as_list(data.get("pages")):
            if not isinstance(raw, dict):
                continue
            path = first_text(raw.get("url"))
            if not path:
                image = first_text(raw.get("image"))
                if image and manga_slug and chapter_slug:
                    path = (
                        f"//manga/{manga_slug}/chapters/{chapter_slug}/"
                        f"{image.lstrip('/')}"
                    )
            url = self._page_url(path)
            if not url:
                continue
            pages.append(
                Page(
                    number=len(pages) + 1,
                    url=url,
                    width=parse_int(raw.get("width")),
                    height=parse_int(raw.get("height")),
                )
            )
        return pages

    def _neighbour_url(self, slug_url: str, value: Any) -> str | None:
        """Build a reader URL from a previous/next object when the API supplies one."""

        if isinstance(value, dict):
            direct = first_text(value.get("url"), value.get("link"))
            if direct:
                if direct.startswith(("http://", "https://")):
                    return direct
                return absolute_url(_SITE_BASE, direct)
            volume = normalize_number(value.get("volume")) or "1"
            number = normalize_number(value.get("number"))
            if number:
                return f"{_SITE_BASE}/ru/manga/{slug_url}/read/v{volume}/c{number}"
            return None
        text = first_text(value)
        if not text:
            return None
        if text.startswith(("http://", "https://")):
            return text
        if text.startswith(("/", "manga/", "ru/")):
            return absolute_url(_SITE_BASE, text)
        volume, number = self._extract_volume_number(
            [part for part in text.split("/") if part]
        )
        if volume and number:
            return f"{_SITE_BASE}/ru/manga/{slug_url}/read/v{volume}/c{number}"
        return None

    async def _search_summary(self, slug_url: str) -> MangaSummary | None:
        slug = slug_url.split("--", 1)[-1] if "--" in slug_url else slug_url
        query = slug.replace("-", " ").strip()
        if not query:
            return None
        try:
            result = await self.search(query, page=1)
        except (UpstreamError, UpstreamTimeoutError) as exc:
            log_event(
                self._logger,
                "mangalib_search_enrichment_failed",
                source=self.info.code,
                slug_url=slug_url,
                error=str(exc),
            )
            return None
        for summary in result.items:
            if summary.source_id == slug_url or summary.slug == slug:
                return summary
        return None

    def _minimal_summary(self, slug_url: str) -> MangaSummary:
        slug = slug_url.split("--", 1)[-1] if "--" in slug_url else slug_url
        title = slug.replace("-", " ").strip() or slug_url
        return MangaSummary(
            source=self.info.code,
            source_id=slug_url,
            slug=slug or None,
            title=title,
            url=f"{_SITE_BASE}/ru/manga/{slug_url}",
        )

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
            f"{_API_BASE}/api/manga",
            params={
                "q": query,
                "site_id[]": "1",
                "page": page,
                "limit": 20,
            },
        )
        if not isinstance(payload, dict):
            raise UpstreamError(
                "MangaLib: search returned an unexpected payload",
                code="invalid_upstream_payload",
                details={"source": self.info.code},
            )
        items = [
            summary
            for summary in (
                self._summary_from_item(item) for item in _as_list(payload.get("data"))
            )
            if summary is not None
        ]
        meta = _as_dict(payload.get("meta"))
        result = SourceSearchResult(
            source=self.info.code,
            items=items,
            page=parse_int(meta.get("current_page")) or page,
            total=parse_int(meta.get("items_count") or meta.get("total")),
            has_next=bool(meta.get("has_next_page")),
            per_page=parse_int(meta.get("per_page")),
        )
        await self.cache_write_model("search", (query, page), result)
        return result

    async def catalogue(
        self,
        page: int = 1,
        *,
        sort: str = "popular",
        limit: int = 60,
    ) -> SourceSearchResult:
        """Paginated MangaLib catalogue.

        The upstream does not expose a total count on this endpoint, so
        ``total``/``total_pages`` stay ``None`` and callers follow
        ``has_next`` until the final page.  The scheduler records the observed
        last page in ``crawl_state`` for ETA reporting.
        """

        if page < 1:
            raise InputValidationError("page must be >= 1", code="invalid_page")
        sort_key = (sort or "popular").strip().casefold()
        upstream_sort = _CATALOGUE_SORTS.get(sort_key)
        if upstream_sort is None:
            raise InputValidationError(
                f"Unsupported catalogue sort '{sort}'",
                code="invalid_sort",
                details={"allowed": sorted(_CATALOGUE_SORTS)},
            )
        page_limit = max(10, min(int(limit or 60), 60))
        cached = await self.cache_read_model(
            "catalogue", (page, sort_key, page_limit), SourceSearchResult
        )
        if cached is not None:
            return cached

        payload = await self.request_json(
            f"{_API_BASE}/api/manga",
            params={
                "site_id[]": "1",
                "page": page,
                "limit": page_limit,
                "sort_by": upstream_sort,
            },
        )
        if not isinstance(payload, dict):
            raise UpstreamError(
                "MangaLib: catalogue returned an unexpected payload",
                code="invalid_upstream_payload",
                details={"source": self.info.code},
            )
        items = [
            summary
            for summary in (
                self._summary_from_item(item) for item in _as_list(payload.get("data"))
            )
            if summary is not None
        ]
        meta = _as_dict(payload.get("meta"))
        links = _as_dict(payload.get("links"))
        current_page = parse_int(meta.get("current_page")) or page
        has_next = bool(meta.get("has_next_page")) or bool(links.get("next"))
        result = SourceSearchResult(
            source=self.info.code,
            items=items,
            page=current_page,
            total=parse_int(meta.get("items_count") or meta.get("total")),
            has_next=has_next,
            per_page=parse_int(meta.get("per_page")) or page_limit,
        )
        await self.cache_write_model(
            "catalogue", (page, sort_key, page_limit), result, ttl=300
        )
        return result

    async def catalog(
        self, page: int = 1, *, sort: str = "popular", limit: int = 60
    ) -> SourceSearchResult:
        """American-spelling alias for :meth:`catalogue`."""

        return await self.catalogue(page, sort=sort, limit=limit)

    async def get_manga(
        self,
        source_id: str = "",
        *,
        url: str | None = None,
        chapters_limit: int = 100,
    ) -> MangaDetail:
        slug_url = self._resolve_manga(source_id, url)
        limit = self.clamp_chapters_limit(chapters_limit)
        cached = await self.cache_read_model("manga", (slug_url, limit), MangaDetail)
        if cached is not None:
            return cached

        slug = slug_url.split("--", 1)[-1] if "--" in slug_url else slug_url
        detail = await self._try_detail(slug_url, slug)
        chapters = await self._fetch_chapters(slug_url)

        summary: MangaSummary | None = None
        if detail:
            summary = self._summary_from_item(detail)
            canonical = first_text(detail.get("slug_url"), detail.get("slug"))
            if canonical:
                slug_url = canonical
        if summary is None:
            summary = await self._search_summary(slug_url)
        if summary is None:
            summary = self._minimal_summary(slug_url)

        if limit:
            selected = chapters[-limit:]
            selected.reverse()
        else:
            selected = []
        latest_chapter = selected[0] if selected else (chapters[-1] if chapters else None)
        if latest_chapter is not None:
            summary = summary.model_copy(update={"latest_chapter": latest_chapter})

        result = MangaDetail(**summary.model_dump(), chapters=selected)
        await self.cache_write_model("manga", (slug_url, limit), result)
        return result

    async def get_chapter(
        self,
        source_id: str = "",
        *,
        url: str | None = None,
    ) -> ChapterDetail:
        slug_url, volume, number = self._resolve_chapter_target(source_id, url)
        cached = await self.cache_read_model(
            "chapter",
            (slug_url, volume, number),
            ChapterDetail,
        )
        if cached is not None:
            return cached

        payload = await self.request_json(
            f"{_API_BASE}/api/manga/{slug_url}/chapter",
            params={"volume": volume, "number": number},
        )
        data = _as_dict(payload.get("data")) if isinstance(payload, dict) else {}
        if not data:
            raise UpstreamError(
                "MangaLib: chapter endpoint returned an unexpected payload",
                code="invalid_upstream_payload",
                details={"source": self.info.code, "slug_url": slug_url},
            )

        pages = self._reader_pages(slug_url, data)
        if not pages:
            raise UpstreamError(
                "MangaLib: chapter has no page images",
                code="pages_unavailable",
                details={
                    "source": self.info.code,
                    "slug_url": slug_url,
                    "volume": volume,
                    "number": number,
                },
            )

        chapter = self._chapter_summary(slug_url, data)
        if chapter is None:
            raise UpstreamError(
                "MangaLib: chapter payload has an unexpected shape",
                code="invalid_upstream_payload",
                details={"source": self.info.code, "slug_url": slug_url},
            )
        chapter = chapter.model_copy(update={"page_count": len(pages)})
        if url:
            chapter = chapter.model_copy(update={"url": url})

        prev_value = (
            data.get("previous")
            or data.get("prev")
            or data.get("prevChapter")
            or data.get("prev_chapter")
        )
        next_value = (
            data.get("next")
            or data.get("nextChapter")
            or data.get("next_chapter")
        )
        detail = ChapterDetail(
            chapter=chapter,
            pages=pages,
            prev_url=self._neighbour_url(slug_url, prev_value),
            next_url=self._neighbour_url(slug_url, next_value),
            is_horizontal=False,
        )
        await self.cache_write_model("chapter", (slug_url, volume, number), detail)
        return detail

    async def latest(self) -> SourceHome:
        cached = await self.cache_read_model("home", (), SourceHome)
        if cached is not None:
            return cached
        popular = await self._catalogue()
        latest = await self._catalogue(sort_by="last_chapter_at")
        home = SourceHome(source=self.info.code, popular=popular, latest=latest)
        await self.cache_write_model("home", (), home)
        return home

    # ------------------------------------------------------------------
    # Identifier resolution
    # ------------------------------------------------------------------

    def _chapter_identity_error(
        self,
        source_id: str,
        url: str | None,
        message: str | None = None,
    ) -> UpstreamError:
        return UpstreamError(
            message
            or (
                "MangaLib: a full chapter URL or "
                "'<slug_url>/<volume>-<number>' source_id is required; "
                "numeric chapter ids cannot be resolved"
            ),
            code="chapter_identity_required",
            details={
                "source": self.info.code,
                "source_id": source_id or None,
                "url": url,
            },
        )

    @staticmethod
    def _extract_volume_number(segments: list[str]) -> tuple[str | None, str | None]:
        volume: str | None = None
        number: str | None = None
        cleaned = [
            segment
            for segment in segments
            if segment.casefold() not in {"read", "chapter"}
        ]
        for segment in cleaned:
            volume_match = _VOLUME_SEGMENT_RE.fullmatch(segment)
            if volume_match:
                volume = normalize_number(volume_match.group("value")) or None
                continue
            number_match = _NUMBER_SEGMENT_RE.fullmatch(segment)
            if number_match:
                number = normalize_number(number_match.group("value")) or None

        if number is None and cleaned:
            candidate = cleaned[-1]
            if "-" in candidate:
                raw_volume, raw_number = candidate.split("-", 1)
                volume = volume or normalize_number(raw_volume) or None
                number = normalize_number(raw_number) or None
            elif _NUMERIC_SEGMENT_RE.fullmatch(candidate):
                number = normalize_number(candidate)

        if volume is None and len(cleaned) >= 2:
            candidate = cleaned[-2]
            if _NUMERIC_SEGMENT_RE.fullmatch(candidate):
                volume = normalize_number(candidate)
        return volume, number

    def _chapter_target_from_url(self, raw_url: str) -> tuple[str, str, str]:
        self.assert_allowed_url(raw_url)
        segments = path_segments(raw_url)
        if _MANGA_PATH not in segments:
            raise self._chapter_identity_error(
                "",
                raw_url,
                "MangaLib: URL must point to /manga/<slug_url>/read/v<volume>/c<number>",
            )
        index = segments.index(_MANGA_PATH)
        if index + 1 >= len(segments):
            raise self._chapter_identity_error("", raw_url)
        slug_url = segments[index + 1]
        volume, number = self._extract_volume_number(segments[index + 2 :])
        if not volume or not number:
            raise self._chapter_identity_error("", raw_url)
        return slug_url, volume, number

    def _resolve_chapter_target(
        self,
        source_id: str,
        url: str | None,
    ) -> tuple[str, str, str]:
        if url:
            return self._chapter_target_from_url(url)
        value = (source_id or "").strip()
        if value.startswith(("http://", "https://")):
            return self._chapter_target_from_url(value)
        parts = [part for part in value.strip("/").split("/") if part]
        if parts and parts[0].casefold() == "ru":
            parts = parts[1:]
        if parts and parts[0].casefold() == _MANGA_PATH:
            parts = parts[1:]
        if len(parts) < 2:
            raise self._chapter_identity_error(source_id, url)
        slug_url = parts[0]
        volume, number = self._extract_volume_number(parts[1:])
        if not volume or not number:
            raise self._chapter_identity_error(source_id, url)
        return slug_url, volume, number

    def _resolve_manga(self, source_id: str, url: str | None) -> str:
        if url:
            self.assert_allowed_url(url)
            segments = path_segments(url)
            if _MANGA_PATH in segments:
                index = segments.index(_MANGA_PATH)
                if index + 1 < len(segments):
                    return segments[index + 1]
            raise InputValidationError(
                "MangaLib: URL must point to /manga/<slug>",
                code="invalid_source_url",
            )
        value = (source_id or "").strip().strip("/")
        if value.startswith(f"{_MANGA_PATH}/"):
            value = value[len(_MANGA_PATH) + 1 :]
        if value.startswith("ru/"):
            value = value[3:]
        if "/" in value:
            value = value.split("/", 1)[0]
        if not value:
            raise InputValidationError(
                "MangaLib: source_id or url is required",
                code="missing_source_id",
            )
        return value
