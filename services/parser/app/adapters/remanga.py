"""Remanga adapter (api.remanga.org).

Verified public JSON endpoints (anonymous, 2026-11-11):

* ``GET /api/v2/search/?query=<q>&page=<n>`` — 20 results per page, ``meta``
  carries ``total_items`` / ``total_pages`` / ``page``.
* ``GET /api/v2/titles/{dir}/`` — title detail.
* ``GET /api/v2/titles/chapters/?branch_id=<id>&page=<n>&ordering=-index`` —
  newest-first chapter list, 30 per page, integer ``next`` page.
* ``GET /api/v2/titles/chapters/{chapter_id}/`` — chapter metadata and reader
  pages (nested page groups).

Reader URLs on the site are ``/manga/{dir}/{chapter_id}``; the legacy
``/manga/{dir}/chapter/{id}`` form is accepted as an input alias.

``https://remanga.org/robots.txt`` disallows ``/api`` (and ``/search``).  The
adapter is therefore disabled by default and must only be enabled by an
operator with explicit permission from the site.  Free reader pages are public;
paid chapters return ``is_paid: true`` with no pages and are rejected with a
typed ``chapter_paid`` error instead of being bypassed.
"""

from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import parse_qs, urlparse

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


class RemangaAdapter(BaseAdapter):
    """Adapter for ``remanga.org`` (opt-in only, disabled by default)."""

    info = SourceInfo(
        code="remanga",
        name="Remanga",
        base_url=_SITE_BASE,
        language="ru",
        enabled=False,
        requires_cookies=False,
        capabilities=SourceCapabilities(
            search=True,
            catalog=False,
            manga=True,
            chapters=True,
            pages=True,
            latest=False,
            requires_auth_for_pages=False,
        ),
        notes=(
            "Public JSON API verified for search, title details, chapter lists "
            "and reader pages. Page images use img3.reimg2.org (no Referer) and "
            "img-reserve.reimg2.org (Referer: https://remanga.org/). "
            "robots.txt disallows /api, so the source is disabled by default; "
            "enable only with explicit permission. Paid chapters are rejected "
            "instead of bypassed."
        ),
    )
    allowed_hosts = frozenset({"remanga.org", "www.remanga.org", "api.remanga.org"})
    max_concurrency = 1
    default_headers: ClassVar[dict[str, str]] = {
        "Accept": "application/json, text/plain, */*",
        "Origin": _SITE_BASE,
        "Referer": f"{_SITE_BASE}/",
    }

    def _configured_cookie(self, settings) -> str | None:  # type: ignore[no-untyped-def]
        return (settings.remanga_cookie or "").strip() or None

    # ------------------------------------------------------------------
    # Mapping
    # ------------------------------------------------------------------

    def _cover_url(self, item: dict[str, Any]) -> str | None:
        cover = _as_dict(item.get("cover"))
        return absolute_url(
            _SITE_BASE,
            first_text(cover.get("mid"), cover.get("high"), cover.get("low")),
        )

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
            url=absolute_url(_SITE_BASE, f"/manga/{directory}") if directory else None,
        )

    def _summary_from_detail(self, title: dict[str, Any]) -> MangaSummary:
        directory = first_text(title.get("dir"))
        genres = [
            first_text(genre.get("name"))
            for genre in [*_as_list(title.get("genres")), *_as_list(title.get("categories"))]
            if isinstance(genre, dict)
        ]
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
            genres=[genre for genre in genres if genre],
            url=absolute_url(_SITE_BASE, f"/manga/{directory}") if directory else None,
        )

    def _chapter_summary(
        self, directory: str | None, item: Any
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
        url = self._chapter_url(directory, chapter_id)
        return ChapterSummary(
            source=self.info.code,
            source_id=str(chapter_id),
            manga_source_id=directory or "",
            volume=volume,
            number=number,
            title=first_text(item.get("name"), f"Глава {number}"),
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

    async def _fetch_chapters(
        self,
        branch_id: int,
        directory: str | None,
        limit: int,
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
            added = False
            for item in rows:
                chapter_id = parse_int(item.get("id"))
                if chapter_id is not None and chapter_id in seen:
                    continue
                chapter = self._chapter_summary(directory, item)
                if chapter is None:
                    continue
                if chapter_id is not None:
                    seen.add(chapter_id)
                chapters.append(chapter)
                added = True
                if len(chapters) >= limit:
                    return chapters[:limit]
            next_page = self._next_page(payload.get("next"))
            if not added or next_page is None or next_page <= page:
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
        )
        await self.cache_write_model("search", (query, page), result)
        return result

    async def get_manga(
        self,
        source_id: str = "",
        *,
        url: str | None = None,
        chapters_limit: int = 100,
    ) -> MangaDetail:
        directory = self._resolve_manga(source_id, url)
        limit = self.clamp_chapters_limit(chapters_limit)
        cached = await self.cache_read_model("manga", (directory, limit), MangaDetail)
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
        chapters = (
            await self._fetch_chapters(branch_id, directory, limit)
            if branch_id is not None and limit
            else []
        )
        latest_chapter = chapters[0] if chapters else None
        summary = self._summary_from_detail(payload)
        if latest_chapter is not None:
            summary = summary.model_copy(update={"latest_chapter": latest_chapter})
        result = MangaDetail(**summary.model_dump(), chapters=chapters)
        await self.cache_write_model("manga", (directory, limit), result)
        return result

    async def get_chapter(
        self,
        source_id: str = "",
        *,
        url: str | None = None,
    ) -> ChapterDetail:
        directory, chapter_id = self._resolve_chapter(source_id, url)
        cached = await self.cache_read_model(
            "chapter",
            (directory or "", chapter_id),
            ChapterDetail,
        )
        if cached is not None:
            return cached

        payload = await self.request_json(f"{_API_BASE}/api/v2/titles/chapters/{chapter_id}/")
        if not isinstance(payload, dict):
            raise UpstreamError(
                "Remanga: chapter returned an unexpected payload",
                code="invalid_upstream_payload",
                details={"source": self.info.code},
            )
        is_paid = bool(payload.get("is_paid"))
        is_bought = bool(payload.get("is_bought"))
        if is_paid and not is_bought:
            raise UpstreamError(
                "Remanga: chapter is paid and cannot be read anonymously",
                code="chapter_paid",
                details={
                    "source": self.info.code,
                    "chapter_id": chapter_id,
                    "title_id": parse_int(payload.get("title_id")),
                    "price": first_text(payload.get("price")) or None,
                },
            )
        if payload.get("is_published") is False:
            raise UpstreamError(
                "Remanga: chapter is not published",
                code="chapter_unpublished",
                details={"source": self.info.code, "chapter_id": chapter_id},
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
                    "is_paid": is_paid,
                    "is_bought": is_bought,
                },
            )

        number = normalize_number(payload.get("chapter")) or "0"
        volume = normalize_number(payload.get("tome")) or None
        chapter_url = self._chapter_url(directory, chapter_id) or url
        chapter = ChapterSummary(
            source=self.info.code,
            source_id=str(chapter_id),
            manga_source_id=directory or "",
            volume=volume,
            number=number,
            title=first_text(payload.get("name"), f"Глава {number}"),
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
        await self.cache_write_model("chapter", (directory or "", chapter_id), detail)
        return detail

    async def latest(self) -> SourceHome:
        # No safe, verified "latest updates" feed: the catalogue endpoint is
        # behind the same /api robots restriction and is not implemented here.
        return SourceHome(source=self.info.code, popular=[], latest=[])

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
