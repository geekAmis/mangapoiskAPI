"""HentaiLib adapter (hentailib.me + hapi.hentaicdn.org).

HentaiLib is an adult-only MangaLib-family source.  Metadata, catalogue,
chapter lists and (when the operator supplies a source session) reader pages
are served by the public JSON API at ``hapi.hentaicdn.org``.  The site itself
is reachable through several domains; the first working base URL is kept for
the lifetime of the process and the rest are used as fallbacks.

The source is disabled by default.  Nothing in this adapter bypasses a login,
paywall, CAPTCHA or DRM: if the upstream reader returns 404/403 the adapter
raises a typed error and the operator must provide an authorised cookie through
the existing parser cookie store.
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

_SITE_BASE = "https://hentailib.me"
_API_BASE = "https://hapi.hentaicdn.org/api"
_SITE_ID = "4"
_VOLUME_SEGMENT_RE = re.compile(r"^v(?P<value>\d+(?:\.\d+)?)$", re.IGNORECASE)
_NUMBER_SEGMENT_RE = re.compile(r"^c(?P<value>\d+(?:\.\d+)?)$", re.IGNORECASE)
_NUMERIC_SEGMENT_RE = re.compile(r"^\d+(?:\.\d+)?$")
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
    """Flatten a ProseMirror document or plain HTML description."""

    if isinstance(value, str):
        return strip_html(value)
    if not isinstance(value, dict):
        return ""
    parts: list[str] = []
    text = value.get("text")
    if isinstance(text, str) and text:
        parts.append(text)
    for child in _as_list(value.get("content")):
        rendered = _rich_text(child)
        if rendered:
            parts.append(rendered)
    joined = " ".join(parts).strip()
    if str(value.get("type") or "") in {"paragraph", "blockquote", "list_item"} and joined:
        return joined + "\n"
    return joined


class HentaiLibAdapter(BaseAdapter):
    """Best-effort adapter for the adult-only HentaiLib source."""

    info = SourceInfo(
        code="hentailib",
        name="HentaiLib",
        base_url=_SITE_BASE,
        language="ru",
        enabled=False,
        requires_cookies=True,
        adult_only=True,
        requires_age_confirmation=True,
        capabilities=SourceCapabilities(
            search=True,
            catalog=True,
            manga=True,
            chapters=True,
            pages=True,
            latest=True,
            requires_auth_for_pages=True,
        ),
        notes=(
            "Adult-only source, disabled by default. Metadata uses the public "
            "hapi.hentaicdn.org JSON API (Site-Id: 4). Reader pages may require "
            "an operator-provided HentaiLib session cookie."
        ),
    )
    max_concurrency = 1
    default_headers: ClassVar[dict[str, str]] = {
        "Accept": "application/json, text/plain, */*",
        "Referer": f"{_SITE_BASE}/",
        "Origin": _SITE_BASE,
        "Site-Id": _SITE_ID,
        "Client-Time-Zone": "Europe/Moscow",
    }

    def __init__(self, client, settings, cache) -> None:  # type: ignore[no-untyped-def]
        base_urls = list(getattr(settings, "hentailib_base_url_list", []) or [_SITE_BASE])
        api_urls = list(getattr(settings, "hentailib_api_base_url_list", []) or [_API_BASE])
        self._base_urls = [url.rstrip("/") for url in base_urls if url.strip()]
        self._api_urls = [url.rstrip("/") for url in api_urls if url.strip()]
        super().__init__(client, settings, cache)
        self.info.base_url = self._base_urls[0]
        self._active_base = self._base_urls[0]
        self._active_api = self._api_urls[0]
        hosts = {
            "hentailib.me",
            "www.hentailib.me",
            "hapi.hentaicdn.org",
            "auth.hentaicdn.org",
            "cover.hentaicdn.org",
            "img.hentaicdn.org",
            "img2.imglib.info",
            "img3.cdnlibs.org",
        }
        for url in self._base_urls + self._api_urls:
            host = urlparse(url).netloc.lower()
            if host:
                hosts.add(host)
        self.allowed_hosts = frozenset(hosts)

    def _configured_cookie(self, settings) -> str | None:  # type: ignore[no-untyped-def]
        return (getattr(settings, "hentailib_cookie", None) or "").strip() or None

    # ------------------------------------------------------------------
    # Upstream helpers with domain fallback
    # ------------------------------------------------------------------

    def _site_headers(self, base: str) -> dict[str, str]:
        return {
            "Referer": f"{base}/",
            "Origin": base,
        }

    async def _site_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Request a site-relative JSON endpoint with domain fallback."""

        bases = [self._active_base, *[url for url in self._base_urls if url != self._active_base]]
        last_error: Exception | None = None
        for base in bases:
            try:
                payload = await self.request_json(
                    f"{base}{path}", params=params, headers=self._site_headers(base)
                )
            except NotFoundError:
                raise
            except (UpstreamError, UpstreamTimeoutError) as exc:
                last_error = exc
                continue
            self._active_base = base
            return payload
        raise last_error or UpstreamError(
            "HentaiLib: no site domain is reachable",
            code="source_unreachable",
            details={"source": self.info.code},
        )

    async def _api_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Request a hapi.hentaicdn.org endpoint with API-host fallback."""

        apis = [self._active_api, *[url for url in self._api_urls if url != self._active_api]]
        last_error: Exception | None = None
        for api in apis:
            try:
                payload = await self.request_json(
                    f"{api}{path}",
                    params={"site_id[]": _SITE_ID, **(params or {})},
                    headers={
                        **self.default_headers,
                        **self._site_headers(self._active_base),
                    },
                )
            except NotFoundError:
                raise
            except (UpstreamError, UpstreamTimeoutError) as exc:
                last_error = exc
                continue
            self._active_api = api
            return payload
        raise last_error or UpstreamError(
            "HentaiLib: no API host is reachable",
            code="source_unreachable",
            details={"source": self.info.code},
        )

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
        source_id = slug_url or slug or (str(numeric_id) if numeric_id is not None else "")
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
        adult = "18+" in age_label or "rx" in age_label.casefold() or self.info.adult_only
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
            rating=parse_float(rating.get("average") or item.get("rating")),
            rating_count=parse_int(rating.get("votes") or item.get("rating_count")),
            poster_url=absolute_url(
                self._active_base,
                first_text(cover.get("default"), cover.get("md"), cover.get("thumbnail")),
            ),
            adult=adult,
            adult_only=True,
            requires_age_confirmation=True,
            genres=[genre for genre in genres if genre],
            url=f"{self._active_base}/ru/manga/{source_id}",
            updated_at=parse_iso_datetime(item.get("last_chapter_at")),
            chapters_count=parse_int(item.get("chap_count") or item.get("items_count")),
        )

    def _chapter_summary(self, manga_slug_url: str, item: Any) -> ChapterSummary | None:
        if not isinstance(item, dict):
            return None
        chapter_id = parse_int(item.get("id"))
        volume = normalize_number(item.get("volume")) or None
        number = normalize_number(item.get("number")) or normalize_number(
            item.get("number_secondary")
        )
        if not number:
            return None
        branches = [branch for branch in _as_list(item.get("branches")) if isinstance(branch, dict)]
        branch = branches[0] if branches else {}
        branch_id = parse_int(branch.get("branch_id") or branch.get("id") or chapter_id)
        translator = None
        teams = [team for team in _as_list(branch.get("teams")) if isinstance(team, dict)]
        if teams:
            translator = first_text(teams[0].get("name")) or None
        published_at = (
            parse_iso_datetime(branch.get("created_at"))
            or parse_iso_datetime(item.get("created_at"))
        )
        source_id = str(chapter_id) if chapter_id is not None else f"{volume or '1'}-{number}"
        url = (
            f"{self._active_base}/ru/manga/{manga_slug_url}/read/"
            f"v{volume or '1'}/c{number}"
        )
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
    # Public adapter API
    # ------------------------------------------------------------------

    async def search(self, query: str, page: int = 1) -> SourceSearchResult:
        query = self.normalise_query(query)
        if page < 1:
            raise InputValidationError("page must be >= 1", code="invalid_page")
        cached = await self.cache_read_model("search", (query, page), SourceSearchResult)
        if cached is not None:
            return cached

        payload = await self._api_json(
            "/manga",
            params={"q": query, "page": page, "limit": 20},
        )
        if not isinstance(payload, dict):
            raise UpstreamError(
                "HentaiLib: search returned an unexpected payload",
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

        payload = await self._api_json(
            "/manga",
            params={
                "q": "",
                "page": page,
                "limit": page_limit,
                "sort_by": upstream_sort,
            },
        )
        if not isinstance(payload, dict):
            raise UpstreamError(
                "HentaiLib: catalogue returned an unexpected payload",
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
        result = SourceSearchResult(
            source=self.info.code,
            items=items,
            page=current_page,
            total=parse_int(meta.get("items_count") or meta.get("total")),
            has_next=bool(meta.get("has_next_page")) or bool(links.get("next")),
            per_page=parse_int(meta.get("per_page")) or page_limit,
        )
        await self.cache_write_model(
            "catalogue", (page, sort_key, page_limit), result, ttl=300
        )
        return result

    async def catalog(
        self, page: int = 1, *, sort: str = "popular", limit: int = 60
    ) -> SourceSearchResult:
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

        detail_payload = await self._api_json(f"/manga/{slug_url}")
        detail = _as_dict(detail_payload.get("data")) if isinstance(detail_payload, dict) else {}
        chapters_payload = await self._api_json(f"/manga/{slug_url}/chapters")
        chapters = [
            chapter
            for chapter in (
                self._chapter_summary(slug_url, item)
                for item in _as_list(_as_dict(chapters_payload).get("data"))
            )
            if chapter is not None
        ]

        summary = self._summary_from_item(detail)
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
        slug_url, volume, number, branch_id = self._resolve_chapter_target(source_id, url)
        cache_parts = (slug_url, volume, number, branch_id or "")
        cached = await self.cache_read_model("chapter", cache_parts, ChapterDetail)
        if cached is not None:
            return cached

        params: dict[str, Any] = {"volume": volume, "number": number}
        if branch_id:
            params["branch_id"] = branch_id
        try:
            payload = await self._api_json(f"/manga/{slug_url}/chapter", params=params)
        except NotFoundError as exc:
            raise UpstreamError(
                "HentaiLib: chapter is unavailable (the source may require an "
                "authenticated session; configure a source cookie)",
                code="chapter_unavailable",
                details={
                    "source": self.info.code,
                    "slug_url": slug_url,
                    "volume": volume,
                    "number": number,
                },
            ) from exc

        data = _as_dict(payload.get("data")) if isinstance(payload, dict) else {}
        if not data:
            raise UpstreamError(
                "HentaiLib: chapter endpoint returned an unexpected payload",
                code="invalid_upstream_payload",
                details={"source": self.info.code, "slug_url": slug_url},
            )
        pages = self._reader_pages(slug_url, data)
        if not pages:
            raise UpstreamError(
                "HentaiLib: chapter has no page images",
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
            chapter = ChapterSummary(
                source=self.info.code,
                source_id=f"{volume}-{number}",
                manga_source_id=slug_url,
                volume=volume,
                number=number,
                title=f"Глава {number}",
                url=url,
            )
        chapter = chapter.model_copy(update={"page_count": len(pages)})
        if url:
            chapter = chapter.model_copy(update={"url": url})

        detail = ChapterDetail(
            chapter=chapter,
            pages=pages,
            prev_url=self._neighbour_url(slug_url, data.get("previous") or data.get("prev")),
            next_url=self._neighbour_url(slug_url, data.get("next")),
            is_horizontal=False,
        )
        await self.cache_write_model("chapter", cache_parts, detail)
        return detail

    async def latest(self) -> SourceHome:
        cached = await self.cache_read_model("home", (), SourceHome)
        if cached is not None:
            return cached
        popular = await self.catalogue(sort="popular")
        latest = await self.catalogue(sort="updated")
        home = SourceHome(
            source=self.info.code,
            popular=popular.items,
            latest=latest.items,
        )
        await self.cache_write_model("home", (), home)
        return home

    # ------------------------------------------------------------------
    # Identifier resolution
    # ------------------------------------------------------------------

    def _reader_pages(self, slug_url: str, data: dict[str, Any]) -> list[Page]:
        raw_pages = _as_list(data.get("pages"))
        attachments = _as_list(data.get("attachments"))
        if not raw_pages and attachments:
            raw_pages = attachments
        pages: list[Page] = []
        for raw in raw_pages:
            if isinstance(raw, dict):
                path = first_text(raw.get("url"), raw.get("link"), raw.get("image"))
                width = parse_int(raw.get("width"))
                height = parse_int(raw.get("height"))
            else:
                path = first_text(raw)
                width = height = None
            if not path:
                continue
            if path.startswith("//"):
                path = f"https:{path}"
            elif not path.startswith(("http://", "https://")):
                path = f"{self._active_base}/{path.lstrip('/')}"
            pages.append(Page(number=len(pages) + 1, url=path, width=width, height=height))
        return pages

    def _neighbour_url(self, slug_url: str, value: Any) -> str | None:
        if isinstance(value, dict):
            volume = normalize_number(value.get("volume")) or "1"
            number = normalize_number(value.get("number"))
            if number:
                return f"{self._active_base}/ru/manga/{slug_url}/read/v{volume}/c{number}"
            direct = first_text(value.get("url"), value.get("link"))
            if direct:
                return absolute_url(self._active_base, direct)
        text = first_text(value)
        if not text:
            return None
        if text.startswith(("http://", "https://")):
            return text
        if text.startswith(("/", "ru/")):
            return absolute_url(self._active_base, text)
        volume, number = self._extract_volume_number([part for part in text.split("/") if part])
        if volume and number:
            return f"{self._active_base}/ru/manga/{slug_url}/read/v{volume}/c{number}"
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
                "hentailib_search_enrichment_failed",
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
            url=f"{self._active_base}/ru/manga/{slug_url}",
            adult=True,
            adult_only=True,
            requires_age_confirmation=True,
        )

    @staticmethod
    def _extract_volume_number(segments: list[str]) -> tuple[str | None, str | None]:
        volume: str | None = None
        number: str | None = None
        cleaned = [
            segment for segment in segments if segment.casefold() not in {"read", "chapter"}
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

    def _chapter_target_from_url(self, raw_url: str) -> tuple[str, str, str, str | None]:
        self.assert_allowed_url(raw_url)
        parsed = urlparse(raw_url)
        segments = path_segments(raw_url)
        if "manga" not in segments:
            raise self._chapter_identity_error(
                "", raw_url, "HentaiLib: URL must point to /manga/<slug>/read/v<volume>/c<number>"
            )
        index = segments.index("manga")
        if index + 1 >= len(segments):
            raise self._chapter_identity_error("", raw_url)
        slug_url = segments[index + 1]
        volume, number = self._extract_volume_number(segments[index + 2 :])
        if not volume or not number:
            raise self._chapter_identity_error("", raw_url)
        branch_id = None
        for part in (parsed.query or "").split("&"):
            key, _, value = part.partition("=")
            if key == "bid" and value:
                branch_id = value
                break
        return slug_url, volume, number, branch_id

    def _chapter_identity_error(
        self,
        source_id: str,
        url: str | None,
        message: str | None = None,
    ) -> UpstreamError:
        return UpstreamError(
            message
            or (
                "HentaiLib: a full chapter URL or "
                "'<slug_url>/<volume>-<number>' source_id is required"
            ),
            code="chapter_identity_required",
            details={"source": self.info.code, "source_id": source_id or None, "url": url},
        )

    def _resolve_chapter_target(
        self,
        source_id: str,
        url: str | None,
    ) -> tuple[str, str, str, str | None]:
        if url:
            return self._chapter_target_from_url(url)
        value = (source_id or "").strip()
        if value.startswith(("http://", "https://")):
            return self._chapter_target_from_url(value)
        parts = [part for part in value.strip("/").split("/") if part]
        if parts and parts[0].casefold() == "ru":
            parts = parts[1:]
        if parts and parts[0].casefold() == "manga":
            parts = parts[1:]
        if len(parts) < 2:
            raise self._chapter_identity_error(source_id, url)
        slug_url = parts[0]
        volume, number = self._extract_volume_number(parts[1:])
        if not volume or not number:
            raise self._chapter_identity_error(source_id, url)
        return slug_url, volume, number, None

    def _resolve_manga(self, source_id: str, url: str | None) -> str:
        if url:
            self.assert_allowed_url(url)
            segments = path_segments(url)
            if "manga" in segments:
                index = segments.index("manga")
                if index + 1 < len(segments):
                    return segments[index + 1]
            raise InputValidationError(
                "HentaiLib: URL must point to /manga/<slug>",
                code="invalid_source_url",
            )
        value = (source_id or "").strip().strip("/")
        if value.startswith("manga/"):
            value = value[len("manga/") :]
        if value.startswith("ru/"):
            value = value[3:]
        if "/" in value:
            value = value.split("/", 1)[0]
        if not value:
            raise InputValidationError(
                "HentaiLib: source_id or url is required",
                code="missing_source_id",
            )
        return value
