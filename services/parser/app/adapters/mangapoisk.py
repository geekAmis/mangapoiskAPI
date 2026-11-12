"""MangaPoisk adapter (Inertia.js + Svelte).

The upstream serves an HTML shell whose ``#app`` element carries the complete
Inertia payload in ``data-page``.  Subsequent page loads can be requested as
JSON by sending ``X-Inertia: true`` and the current ``X-Inertia-Version``.

Only public catalogue pages are fetched.  An optional operator-supplied cookie
can be configured through ``MANGAPOISK_COOKIE``; it is never logged, cached or
returned to clients.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from manga_common.errors import NotFoundError, UpstreamError
from manga_common.errors import ValidationError as InputValidationError
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
    number_from_path_segment,
    parse_ru_date,
    path_segments,
)

_MANGA_PATH = "manga"

# Upstream ``sortBy`` values observed on /manga.
_CATALOGUE_SORTS: dict[str, str] = {
    "popular": "popular",
    "updated": "-last_chapter_at",
    "new": "-published_at",
    "rating": "popular",
    "title": "name",
    "chapters": "-chapters_count",
}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _genre_labels(value: Any) -> list[str]:
    return [
        first_text(genre.get("title"), genre.get("name_en"), genre.get("name"))
        for genre in _as_list(value)
        if isinstance(genre, dict)
    ]


def parse_inertia_html(text: str) -> dict[str, Any]:
    """Extract and decode the Inertia payload from an HTML document."""

    soup = BaseAdapter.parse_html(text)
    element = soup.find(id="app") or soup.find(attrs={"data-page": True})
    raw = element.get("data-page") if element is not None else None
    if not raw:
        raise UpstreamError(
            "MangaPoisk: page does not contain an Inertia payload",
            code="invalid_upstream_payload",
            details={"source": "mangapoisk"},
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UpstreamError(
            "MangaPoisk: Inertia payload is not valid JSON",
            code="invalid_upstream_payload",
            details={"source": "mangapoisk"},
        ) from exc
    if not isinstance(payload, dict):
        raise UpstreamError(
            "MangaPoisk: Inertia payload has an unexpected shape",
            code="invalid_upstream_payload",
            details={"source": "mangapoisk"},
        )
    return payload


class MangaPoiskAdapter(BaseAdapter):
    """Full adapter for ``mangapoisk.me``."""

    info = SourceInfo(
        code="mangapoisk",
        name="MangaPoisk",
        base_url="https://mangapoisk.me",
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
        notes="Public catalogue; optional cookie only for operator sessions.",
    )
    allowed_hosts = frozenset({"mangapoisk.me", "www.mangapoisk.me"})
    max_concurrency = 2
    default_headers: ClassVar[dict[str, str]] = {"Accept": "text/html, application/xhtml+xml, application/json"}

    def __init__(self, client, settings, cache) -> None:  # type: ignore[no-untyped-def]
        super().__init__(client, settings, cache)
        self._version: str | None = None

    def _configured_cookie(self, settings) -> str | None:  # type: ignore[no-untyped-def]
        return (settings.mangapoisk_cookie or "").strip() or None

    # ------------------------------------------------------------------
    # Inertia negotiation
    # ------------------------------------------------------------------

    async def _fetch_home_document(self, *, force: bool = False) -> dict[str, Any]:
        if not force:
            cached = await self.cache_read_json("home-document")
            if isinstance(cached, dict) and isinstance(cached.get("props"), dict):
                version = str(cached.get("version") or "")
                if version:
                    self._version = version
                return cached

        await self.ensure_robots_allowed("/")
        text = await self.request_text("/")
        payload = parse_inertia_html(text)
        if not isinstance(payload.get("props"), dict):
            raise UpstreamError(
                "MangaPoisk: home payload has no props",
                code="invalid_upstream_payload",
                details={"source": self.info.code},
            )
        version = str(payload.get("version") or "")
        if version:
            self._version = version
            await self.cache_write_json(
                "inertia-version",
                version,
                ttl=max(self.cache_ttl, 3600),
            )
        await self.cache_write_json("home-document", payload)
        return payload

    async def _ensure_version(self, *, force: bool = False) -> str:
        if not force and self._version:
            return self._version
        if not force:
            cached = await self.cache_read_json("inertia-version")
            if isinstance(cached, str) and cached:
                self._version = cached
                return cached
        document = await self._fetch_home_document(force=force)
        version = str(document.get("version") or "")
        if not version:
            raise UpstreamError(
                "MangaPoisk: home payload does not expose an Inertia version",
                code="inertia_version_missing",
                details={"source": self.info.code},
            )
        self._version = version
        return version

    async def _inertia_get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        refreshed = False
        for _ in range(2):
            version = await self._ensure_version()
            headers = {
                "X-Inertia": "true",
                "X-Inertia-Version": version,
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "text/html, application/xhtml+xml",
            }
            try:
                response = await self.request("GET", path, params=params, headers=headers)
            except UpstreamError as exc:
                status_code = exc.details.get("status_code") if isinstance(exc.details, dict) else None
                if status_code in {409, 419} and not refreshed:
                    await self._ensure_version(force=True)
                    refreshed = True
                    continue
                raise

            try:
                payload = response.json()
            except ValueError as exc:
                raise UpstreamError(
                    "MangaPoisk: Inertia response is not valid JSON",
                    code="invalid_upstream_json",
                    details={"source": self.info.code},
                ) from exc
            if not isinstance(payload, dict):
                raise UpstreamError(
                    "MangaPoisk: Inertia response has an unexpected shape",
                    code="invalid_upstream_payload",
                    details={"source": self.info.code},
                )

            component = str(payload.get("component") or "")
            if component.startswith("Error/"):
                props = _as_dict(payload.get("props"))
                status = parse_int(props.get("status"))
                if status == 404:
                    raise NotFoundError(
                        "MangaPoisk: page not found",
                        code="not_found",
                        details={"source": self.info.code},
                    )
                raise UpstreamError(
                    "MangaPoisk: upstream returned an error page",
                    code="upstream_error_page",
                    details={"source": self.info.code, "status": status},
                )

            payload_version = str(payload.get("version") or "")
            if payload_version and payload_version != version:
                if refreshed:
                    raise UpstreamError(
                        "MangaPoisk: Inertia version negotiation failed",
                        code="inertia_version_mismatch",
                        details={"source": self.info.code},
                    )
                await self._ensure_version(force=True)
                refreshed = True
                continue
            return payload

        raise UpstreamError(
            "MangaPoisk: Inertia version negotiation failed",
            code="inertia_version_mismatch",
            details={"source": self.info.code},
        )

    # ------------------------------------------------------------------
    # Mapping
    # ------------------------------------------------------------------

    def _chapter_summary(self, manga_slug: str, item: dict[str, Any]) -> ChapterSummary:
        link = first_text(item.get("link"))
        segments = path_segments(link) if link else []
        slug = manga_slug
        segment = ""
        if len(segments) >= 4 and segments[-2] == "chapter":
            slug = segments[-3]
            segment = segments[-1]
        if not segment:
            volume_hint = normalize_number(item.get("volume"))
            number_hint = normalize_number(item.get("number"))
            segment = f"{volume_hint}-{number_hint}" if volume_hint else number_hint
        volume_from_path, number_from_segment = number_from_path_segment(segment)
        volume = normalize_number(item.get("volume")) or volume_from_path
        number = normalize_number(item.get("number")) or number_from_segment or "0"
        source_id = f"{slug}/{segment}" if segment else f"{slug}/{number}"
        title = first_text(item.get("name"), item.get("title"), f"Глава {number}")
        return ChapterSummary(
            source=self.info.code,
            source_id=source_id,
            manga_source_id=slug,
            volume=volume or None,
            number=number,
            title=title,
            published_at=parse_ru_date(first_text(item.get("formattedDate"))),
            page_count=parse_int(item.get("page_count")) or 0,
            url=absolute_url(self.info.base_url, link) if link else None,
            is_external=bool(item.get("is_external_link")),
        )

    def _manga_summary(
        self,
        manga: dict[str, Any],
        *,
        latest_chapter: ChapterSummary | None = None,
    ) -> MangaSummary:
        slug = first_text(manga.get("slug"))
        link = first_text(manga.get("link"))
        if not slug and link:
            segments = path_segments(link)
            if len(segments) >= 2 and segments[-2] == _MANGA_PATH:
                slug = segments[-1]
        poster = _as_dict(manga.get("poster"))
        genres = _genre_labels(manga.get("genres"))
        latest_item = _as_dict(manga.get("lastChapter"))
        updated_at = parse_ru_date(first_text(latest_item.get("formattedDate")))
        if latest_chapter is None and latest_item and slug:
            latest_chapter = self._chapter_summary(slug, latest_item)
        return MangaSummary(
            source=self.info.code,
            source_id=slug or first_text(manga.get("id")),
            slug=slug or None,
            title=first_text(manga.get("title"), manga.get("name"), slug),
            title_en=first_text(manga.get("name_en")) or None,
            title_alt=first_text(manga.get("name_alt"), manga.get("name_jp")) or None,
            description=strip_html(manga.get("description")) or None,
            year=parse_year(manga.get("year")),
            status=None,
            content_type=None,
            rating=parse_float(manga.get("rating")),
            rating_count=parse_int(manga.get("ratesCount")),
            poster_url=absolute_url(
                self.info.base_url,
                first_text(poster.get("link"), poster.get("link_mini")),
            ),
            adult=bool(manga.get("adult"))
            or any("18+" in genre or "взросл" in genre.casefold() for genre in genres),
            genres=[genre for genre in genres if genre],
            url=absolute_url(self.info.base_url, link or f"/manga/{slug}"),
            updated_at=updated_at,
            latest_chapter=latest_chapter,
            chapters_count=parse_int(manga.get("chapters_count")),
        )

    def _summary_from_card(self, card: Any) -> MangaSummary | None:
        if not isinstance(card, dict):
            return None
        slug = first_text(card.get("slug"))
        link = first_text(card.get("link"))
        if not slug and link:
            segments = path_segments(link)
            if len(segments) >= 2 and segments[-2] == _MANGA_PATH:
                slug = segments[-1]
        if not slug:
            return None
        poster = _as_dict(card.get("poster"))
        last_chapter = _as_dict(card.get("lastChapter"))
        chapters = [item for item in _as_list(card.get("chapters")) if isinstance(item, dict)]
        latest_item = last_chapter or (chapters[0] if chapters else {})
        latest_chapter = self._chapter_summary(slug, latest_item) if latest_item else None
        genres = _genre_labels(card.get("genres"))
        return MangaSummary(
            source=self.info.code,
            source_id=slug,
            slug=slug,
            title=first_text(card.get("title"), card.get("name"), slug),
            description=strip_html(card.get("description")) or None,
            year=parse_year(card.get("year")),
            rating=parse_float(card.get("rating")),
            rating_count=parse_int(card.get("ratesCount")),
            poster_url=absolute_url(
                self.info.base_url,
                first_text(poster.get("link"), poster.get("link_mini")),
            ),
            adult=bool(card.get("adult")),
            genres=[genre for genre in genres if genre],
            url=absolute_url(self.info.base_url, link or f"/manga/{slug}"),
            updated_at=parse_ru_date(first_text(latest_item.get("formattedDate"))),
            latest_chapter=latest_chapter,
            chapters_count=parse_int(card.get("chapters_count")),
        )

    def _summary_from_search(self, item: Any) -> MangaSummary | None:
        if not isinstance(item, dict):
            return None
        link = first_text(item.get("link"))
        segments = path_segments(link)
        slug = segments[-1] if len(segments) >= 2 and segments[-2] == _MANGA_PATH else ""
        if not slug:
            return None
        return MangaSummary(
            source=self.info.code,
            source_id=slug,
            slug=slug,
            title=first_text(item.get("label"), item.get("value"), slug),
            year=parse_year(item.get("year")),
            poster_url=absolute_url(self.info.base_url, first_text(item.get("image"))),
            url=absolute_url(self.info.base_url, link),
        )

    def _pages(self, raw_pages: Any) -> list[Page]:
        pages: list[Page] = []
        for raw in _as_list(raw_pages):
            if not isinstance(raw, dict):
                continue
            url = absolute_url(self.info.base_url, first_text(raw.get("link")))
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

    @staticmethod
    def _chapter_page(value: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if isinstance(value, dict):
            data = [item for item in _as_list(value.get("data")) if isinstance(item, dict)]
            meta = _as_dict(value.get("meta"))
            return data, meta
        return [item for item in _as_list(value) if isinstance(item, dict)], {}

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

        # The site's quick search is not paginated.
        if page > 1:
            result = SourceSearchResult(
                source=self.info.code,
                items=[],
                page=page,
                total=None,
                has_next=False,
            )
            await self.cache_write_model("search", (query, page), result)
            return result

        await self.ensure_robots_allowed("/search")
        payload = await self.request_json(
            "/search",
            params={"q": query},
            headers={"Accept": "application/json, text/plain, */*"},
        )
        if not isinstance(payload, dict):
            raise UpstreamError(
                "MangaPoisk: search returned an unexpected payload",
                code="invalid_upstream_payload",
                details={"source": self.info.code},
            )
        items = [
            summary
            for summary in (self._summary_from_search(item) for item in _as_list(payload.get("results")))
            if summary is not None
        ]
        result = SourceSearchResult(
            source=self.info.code,
            items=items,
            page=1,
            total=len(items),
            has_next=False,
        )
        await self.cache_write_model("search", (query, page), result)
        return result

    async def catalogue(
        self,
        page: int = 1,
        *,
        sort: str = "popular",
        limit: int = 40,
    ) -> SourceSearchResult:
        """Paginated public catalogue (``/manga?page=N&sortBy=...``).

        The upstream is an Inertia page.  Asking for JSON keeps the response
        small; ``total``/``last_page`` are taken from Laravel's paginator.
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
        cached = await self.cache_read_model(
            "catalogue", (page, sort_key), SourceSearchResult
        )
        if cached is not None:
            return cached

        await self.ensure_robots_allowed("/manga")
        payload = await self._inertia_get(
            "/manga",
            params={"page": page, "sortBy": upstream_sort},
        )
        props = _as_dict(payload.get("props"))
        listing = _as_dict(props.get("mangaList"))
        meta = _as_dict(listing.get("meta"))
        items = [
            summary
            for summary in (
                self._manga_summary(item)
                for item in _as_list(listing.get("data"))
                if isinstance(item, dict)
            )
            if summary is not None
        ]
        current_page = parse_int(meta.get("current_page")) or page
        total = parse_int(meta.get("total"))
        per_page = parse_int(meta.get("per_page")) or (limit or None) or 40
        total_pages = parse_int(meta.get("last_page"))
        if total_pages is None and total and per_page:
            total_pages = (total + per_page - 1) // per_page
        result = SourceSearchResult(
            source=self.info.code,
            items=items,
            page=current_page,
            total=total,
            has_next=(
                current_page < total_pages
                if total_pages is not None
                else bool(_as_dict(listing.get("links")).get("next"))
            ),
            total_pages=total_pages,
            per_page=per_page,
        )
        # Catalogue pages are refreshed by the scheduler every 10-15 minutes.
        await self.cache_write_model("catalogue", (page, sort_key), result, ttl=300)
        return result

    async def catalog(
        self, page: int = 1, *, sort: str = "popular", limit: int = 40
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
        slug = self._resolve_manga(source_id, url)
        limit = self.clamp_chapters_limit(chapters_limit)
        cached = await self.cache_read_model(
            "manga",
            (slug, limit),
            MangaDetail,
        )
        if cached is not None:
            return cached

        await self.ensure_robots_allowed(f"/manga/{slug}")
        payload = await self._inertia_get(f"/manga/{slug}", params={"tab": "chapters"})
        props = _as_dict(payload.get("props"))
        manga = _as_dict(_as_dict(props.get("manga")).get("data"))
        if not manga:
            raise NotFoundError(
                "MangaPoisk: manga not found",
                code="not_found",
                details={"source": self.info.code, "source_id": source_id},
            )
        canonical_slug = first_text(manga.get("slug")) or slug

        chapter_rows, meta = self._chapter_page(props.get("chapters"))
        chapters = [self._chapter_summary(canonical_slug, item) for item in chapter_rows]
        if limit > len(chapters):
            last_page = parse_int(meta.get("last_page")) or 1
            page = 2
            seen = {chapter.source_id for chapter in chapters}
            while len(chapters) < limit and page <= last_page:
                page_payload = await self._inertia_get(
                    f"/manga/{canonical_slug}",
                    params={"tab": "chapters", "page": page},
                )
                page_rows, _ = self._chapter_page(_as_dict(page_payload.get("props")).get("chapters"))
                added = 0
                for row in page_rows:
                    chapter = self._chapter_summary(canonical_slug, row)
                    if chapter.source_id in seen:
                        continue
                    seen.add(chapter.source_id)
                    chapters.append(chapter)
                    added += 1
                if not added:
                    break
                page += 1

        unique: list[ChapterSummary] = []
        seen_ids: set[str] = set()
        for chapter in chapters:
            if chapter.source_id in seen_ids:
                continue
            seen_ids.add(chapter.source_id)
            unique.append(chapter)
        if limit:
            unique = unique[:limit]
        else:
            unique = []

        latest_item = _as_dict(manga.get("lastChapter"))
        latest_chapter = self._chapter_summary(canonical_slug, latest_item) if latest_item else None
        if latest_chapter is not None and limit and latest_chapter.source_id not in seen_ids:
            unique = [latest_chapter, *unique][:limit]

        first_item = _as_dict(manga.get("firstChapter"))
        if first_item and limit and len(unique) < limit:
            first_chapter = self._chapter_summary(canonical_slug, first_item)
            if first_chapter.source_id not in {chapter.source_id for chapter in unique}:
                unique.append(first_chapter)

        summary = self._manga_summary(manga, latest_chapter=latest_chapter)
        detail = MangaDetail(**summary.model_dump(), chapters=unique)
        await self.cache_write_model("manga", (slug, limit), detail)
        return detail

    async def get_chapter(
        self,
        source_id: str = "",
        *,
        url: str | None = None,
    ) -> ChapterDetail:
        slug, segment = self._resolve_chapter(source_id, url)
        cached = await self.cache_read_model("chapter", (slug, segment), ChapterDetail)
        if cached is not None:
            return cached

        await self.ensure_robots_allowed(f"/manga/{slug}/chapter/{segment}")
        payload = await self._inertia_get(f"/manga/{slug}/chapter/{segment}")
        props = _as_dict(payload.get("props"))
        chapter_data = _as_dict(_as_dict(props.get("chapter")).get("data"))
        if not chapter_data:
            raise NotFoundError(
                "MangaPoisk: chapter not found",
                code="not_found",
                details={"source": self.info.code, "source_id": source_id},
            )

        chapter = self._chapter_summary(slug, chapter_data)
        next_item = _as_dict(chapter_data.get("nextChapter"))
        next_url = absolute_url(self.info.base_url, first_text(next_item.get("link"))) if next_item else None
        detail = ChapterDetail(
            chapter=chapter,
            # Some licensed/upcoming chapters legitimately expose zero pages.
            pages=self._pages(chapter_data.get("pages")),
            prev_url=None,
            next_url=next_url,
            is_horizontal=bool(
                chapter_data.get("is_horizontal") or chapter_data.get("auto_is_horizontal")
            ),
        )
        await self.cache_write_model("chapter", (slug, segment), detail)
        return detail

    async def latest(self) -> SourceHome:
        cached = await self.cache_read_model("home", (), SourceHome)
        if cached is not None:
            return cached

        document = await self._fetch_home_document()
        props = _as_dict(document.get("props"))
        popular_rows = _as_list(_as_dict(props.get("popular")).get("data"))
        latest_rows = _as_list(_as_dict(props.get("latestUpdated")).get("data"))
        if not popular_rows and not latest_rows:
            raise UpstreamError(
                "MangaPoisk: home payload contains no catalogue lists",
                code="invalid_upstream_payload",
                details={"source": self.info.code},
            )
        home = SourceHome(
            source=self.info.code,
            popular=[
                summary
                for summary in (self._summary_from_card(item) for item in popular_rows)
                if summary is not None
            ],
            latest=[
                summary
                for summary in (self._summary_from_card(item) for item in latest_rows)
                if summary is not None
            ],
        )
        await self.cache_write_model("home", (), home)
        return home

    # ------------------------------------------------------------------
    # Identifier resolution
    # ------------------------------------------------------------------

    def _resolve_manga(self, source_id: str, url: str | None) -> str:
        if url:
            self.assert_allowed_url(url)
            segments = path_segments(url)
            if _MANGA_PATH in segments:
                index = segments.index(_MANGA_PATH)
                if index + 1 < len(segments):
                    return segments[index + 1]
            raise InputValidationError(
                "MangaPoisk: URL must point to /manga/<slug>",
                code="invalid_source_url",
            )
        value = (source_id or "").strip().strip("/")
        if value.startswith(f"{_MANGA_PATH}/"):
            value = value[len(_MANGA_PATH) + 1 :]
        if "/" in value:
            value = value.split("/", 1)[0]
        if not value:
            raise InputValidationError(
                "MangaPoisk: source_id or url is required",
                code="missing_source_id",
            )
        return value

    def _resolve_chapter(self, source_id: str, url: str | None) -> tuple[str, str]:
        if url:
            self.assert_allowed_url(url)
            segments = path_segments(url)
            if _MANGA_PATH in segments:
                index = segments.index(_MANGA_PATH)
                if (
                    index + 3 < len(segments)
                    and segments[index + 2] == "chapter"
                    and segments[index + 1]
                    and segments[index + 3]
                ):
                    return segments[index + 1], segments[index + 3]
            raise InputValidationError(
                "MangaPoisk: URL must point to /manga/<slug>/chapter/<segment>",
                code="invalid_source_url",
            )
        value = (source_id or "").strip().strip("/")
        if value.startswith(f"{_MANGA_PATH}/"):
            value = value[len(_MANGA_PATH) + 1 :]
        parts = [part for part in value.split("/") if part]
        if len(parts) >= 2:
            slug = parts[0]
            rest = parts[1:]
            if rest and rest[0] == "chapter":
                rest = rest[1:]
            if len(rest) == 1:
                return slug, rest[0]
            if len(rest) >= 2:
                return slug, f"{rest[0]}-{rest[1]}"
        raise InputValidationError(
            "MangaPoisk: source_id must be '<manga-slug>/<volume>-<number>' or a url must be provided",
            code="invalid_source_id",
        )
