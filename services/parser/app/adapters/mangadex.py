"""MangaDex adapter (public API).

MangaDex is not a Russian site, but it hosts Russian scanlation groups.  The
adapter filters feeds with ``translatedLanguage[]=ru``.  Network access is
blocked from the development environment, so the adapter is disabled by default
and exercised with fixtures only.
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar
from urllib.parse import quote

from manga_common.errors import (
    NotFoundError,
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
from manga_common.text import parse_int, parse_year, strip_html

from .base import BaseAdapter
from .parsing import (
    first_text,
    normalize_number,
    parse_iso_datetime,
    path_segments,
)

_API_BASE = "https://api.mangadex.org"
_SITE_BASE = "https://mangadex.org"
_TITLE_PATHS = {"title", "manga"}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _localised(value: Any, preferred: tuple[str, ...] = ("ru", "en")) -> str:
    mapping = _as_dict(value)
    for language in preferred:
        text = first_text(mapping.get(language))
        if text:
            return text
    for candidate in mapping.values():
        text = first_text(candidate)
        if text:
            return text
    return ""


class MangaDexAdapter(BaseAdapter):
    """Adapter for ``api.mangadex.org`` (disabled by default)."""

    info = SourceInfo(
        code="mangadex",
        name="MangaDex",
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
        ),
        notes=(
            "Public API with Russian translatedLanguage filter. Network access is "
            "blocked in the development environment; disabled until verified."
        ),
    )
    allowed_hosts = frozenset({"api.mangadex.org", "mangadex.org", "www.mangadex.org"})
    max_concurrency = 2
    default_headers: ClassVar[dict[str, str]] = {"Accept": "application/json"}

    # ------------------------------------------------------------------
    # Mapping
    # ------------------------------------------------------------------

    def _cover_url(self, manga_id: str, relationships: Any) -> str | None:
        for relationship in _as_list(relationships):
            item = _as_dict(relationship)
            if item.get("type") != "cover_art":
                continue
            filename = first_text(_as_dict(item.get("attributes")).get("fileName"))
            if filename:
                return f"https://uploads.mangadex.org/covers/{manga_id}/{filename}.256.jpg"
        return None

    def _summary_from_manga(self, item: Any) -> MangaSummary | None:
        if not isinstance(item, dict):
            return None
        manga_id = first_text(item.get("id"))
        attributes = _as_dict(item.get("attributes"))
        if not manga_id or not attributes:
            return None
        titles = _as_dict(attributes.get("title"))
        title = _localised(titles) or manga_id
        title_en = first_text(titles.get("en")) or None
        alt = ""
        for candidate in _as_list(attributes.get("altTitles")):
            alt = _localised(candidate)
            if alt and alt != title:
                break
        tags: list[str] = []
        for tag in _as_list(attributes.get("tags")):
            name = _localised(_as_dict(_as_dict(tag).get("attributes")).get("name"))
            if name:
                tags.append(name)
        content_rating = first_text(attributes.get("contentRating")).casefold()
        original_language = first_text(attributes.get("originalLanguage")).casefold()
        content_type = {
            "ja": "manga",
            "ko": "manhwa",
            "zh": "manhua",
            "zh-hk": "manhua",
        }.get(original_language)
        return MangaSummary(
            source=self.info.code,
            source_id=manga_id,
            title=title,
            title_en=title_en,
            title_alt=alt if alt and alt != title else None,
            description=strip_html(_localised(attributes.get("description"))) or None,
            year=parse_year(attributes.get("year")),
            status=first_text(attributes.get("status")) or None,
            content_type=content_type,
            poster_url=self._cover_url(manga_id, item.get("relationships")),
            adult=content_rating in {"erotica", "pornographic"},
            genres=tags,
            url=f"{_SITE_BASE}/title/{manga_id}",
        )

    def _chapter_summary(self, item: Any, manga_id: str) -> ChapterSummary | None:
        if not isinstance(item, dict):
            return None
        chapter_id = first_text(item.get("id"))
        attributes = _as_dict(item.get("attributes"))
        if not chapter_id or not attributes:
            return None
        number = normalize_number(attributes.get("chapter")) or "0"
        volume = normalize_number(attributes.get("volume")) or None
        return ChapterSummary(
            source=self.info.code,
            source_id=chapter_id,
            manga_source_id=manga_id,
            volume=volume,
            number=number,
            title=first_text(attributes.get("title"), f"Глава {number}"),
            published_at=parse_iso_datetime(attributes.get("publishAt")),
            page_count=parse_int(attributes.get("pages")) or 0,
            url=f"{_SITE_BASE}/chapter/{chapter_id}",
            is_external=bool(attributes.get("externalUrl")),
        )

    # ------------------------------------------------------------------
    # Upstream helpers
    # ------------------------------------------------------------------

    async def _fetch_feed(
        self,
        manga_id: str,
        limit: int,
    ) -> list[ChapterSummary]:
        chapters: list[ChapterSummary] = []
        offset = 0
        while len(chapters) < limit and offset <= 10_000:
            payload = await self.request_json(
                f"{_API_BASE}/manga/{manga_id}/feed",
                params={
                    "translatedLanguage[]": "ru",
                    "order[volume]": "desc",
                    "order[chapter]": "desc",
                    "limit": min(100, max(1, limit - len(chapters))),
                    "offset": offset,
                },
            )
            if not isinstance(payload, dict):
                raise UpstreamError(
                    "MangaDex: feed returned an unexpected payload",
                    code="invalid_upstream_payload",
                    details={"source": self.info.code},
                )
            rows = [item for item in _as_list(payload.get("data")) if isinstance(item, dict)]
            if not rows:
                break
            for item in rows:
                chapter = self._chapter_summary(item, manga_id)
                if chapter is not None:
                    chapters.append(chapter)
                if len(chapters) >= limit:
                    break
            total = parse_int(payload.get("total"))
            offset += len(rows)
            if total is not None and offset >= total:
                break
        return chapters[:limit]

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
        limit = 20
        offset = (page - 1) * limit
        payload = await self.request_json(
            f"{_API_BASE}/manga",
            params={
                "title": query,
                "translatedLanguage[]": "ru",
                "includes[]": "cover_art",
                "contentRating[]": ("safe", "suggestive", "erotica"),
                "limit": limit,
                "offset": offset,
            },
        )
        if not isinstance(payload, dict):
            raise UpstreamError(
                "MangaDex: search returned an unexpected payload",
                code="invalid_upstream_payload",
                details={"source": self.info.code},
            )
        items = [
            summary
            for summary in (
                self._summary_from_manga(item) for item in _as_list(payload.get("data"))
            )
            if summary is not None
        ]
        total = parse_int(payload.get("total"))
        result = SourceSearchResult(
            source=self.info.code,
            items=items,
            page=page,
            total=total,
            has_next=total is not None and offset + len(items) < total,
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
        manga_id = self._resolve_manga_id(source_id, url)
        limit = self.clamp_chapters_limit(chapters_limit)
        cached = await self.cache_read_model("manga", (manga_id, limit), MangaDetail)
        if cached is not None:
            return cached
        payload = await self.request_json(
            f"{_API_BASE}/manga/{manga_id}",
            params={"includes[]": "cover_art"},
        )
        manga = _as_dict(_as_dict(payload).get("data")) if isinstance(payload, dict) else {}
        if not manga:
            raise NotFoundError(
                "MangaDex: manga not found",
                code="not_found",
                details={"source": self.info.code, "source_id": source_id},
            )
        summary = self._summary_from_manga(manga)
        if summary is None:
            raise UpstreamError(
                "MangaDex: manga payload has an unexpected shape",
                code="invalid_upstream_payload",
                details={"source": self.info.code},
            )
        chapters = await self._fetch_feed(manga_id, limit) if limit else []
        latest_chapter = chapters[0] if chapters else None
        if latest_chapter is not None:
            summary = summary.model_copy(update={"latest_chapter": latest_chapter})
        result = MangaDetail(**summary.model_dump(), chapters=chapters)
        await self.cache_write_model("manga", (manga_id, limit), result)
        return result

    async def get_chapter(
        self,
        source_id: str = "",
        *,
        url: str | None = None,
    ) -> ChapterDetail:
        chapter_id = self._resolve_chapter_id(source_id, url)
        cached = await self.cache_read_model("chapter", (chapter_id,), ChapterDetail)
        if cached is not None:
            return cached

        payload = await self.request_json(
            f"{_API_BASE}/chapter/{chapter_id}",
            params={"includes[]": "manga"},
        )
        chapter_data = _as_dict(_as_dict(payload).get("data")) if isinstance(payload, dict) else {}
        if not chapter_data:
            raise NotFoundError(
                "MangaDex: chapter not found",
                code="not_found",
                details={"source": self.info.code, "source_id": source_id},
            )
        attributes = _as_dict(chapter_data.get("attributes"))
        if attributes.get("externalUrl"):
            raise UpstreamError(
                "MangaDex: chapter is hosted externally and has no page images",
                code="external_chapter",
                details={"source": self.info.code, "source_id": source_id},
            )
        manga_id = ""
        for relationship in _as_list(chapter_data.get("relationships")):
            item = _as_dict(relationship)
            if item.get("type") == "manga":
                manga_id = first_text(item.get("id"))
                break

        at_home = await self.request_json(f"{_API_BASE}/at-home/server/{chapter_id}")
        if not isinstance(at_home, dict):
            raise UpstreamError(
                "MangaDex: at-home server returned an unexpected payload",
                code="invalid_upstream_payload",
                details={"source": self.info.code},
            )
        base_url = first_text(at_home.get("baseUrl")).rstrip("/")
        chapter_info = _as_dict(at_home.get("chapter"))
        image_hash = first_text(chapter_info.get("hash"))
        filenames = [first_text(name) for name in _as_list(chapter_info.get("data"))]
        path_prefix = "data"
        if not filenames:
            filenames = [first_text(name) for name in _as_list(chapter_info.get("dataSaver"))]
            path_prefix = "data-saver"
        pages: list[Page] = []
        for filename in filenames:
            if not filename or not base_url or not image_hash:
                continue
            pages.append(
                Page(
                    number=len(pages) + 1,
                    url=f"{base_url}/{path_prefix}/{image_hash}/{quote(filename, safe='')}",
                )
            )
        if not pages:
            raise UpstreamError(
                "MangaDex: at-home server returned no page data",
                code="pages_unavailable",
                details={"source": self.info.code, "source_id": source_id},
            )
        chapter = self._chapter_summary(chapter_data, manga_id)
        if chapter is None:
            raise UpstreamError(
                "MangaDex: chapter payload has an unexpected shape",
                code="invalid_upstream_payload",
                details={"source": self.info.code},
            )
        chapter = chapter.model_copy(update={"page_count": len(pages)})
        detail = ChapterDetail(
            chapter=chapter,
            pages=pages,
            prev_url=None,
            next_url=None,
            is_horizontal=False,
        )
        await self.cache_write_model("chapter", (chapter_id,), detail)
        return detail

    async def latest(self) -> SourceHome:
        # No verified "latest" feed is implemented for this disabled adapter.
        return SourceHome(source=self.info.code, popular=[], latest=[])

    # ------------------------------------------------------------------
    # Identifier resolution
    # ------------------------------------------------------------------

    def _resolve_manga_id(self, source_id: str, url: str | None) -> str:
        if url:
            self.assert_allowed_url(url)
            segments = path_segments(url)
            for path in _TITLE_PATHS:
                if path in segments:
                    index = segments.index(path)
                    if index + 1 < len(segments):
                        return self._ensure_uuid(segments[index + 1])
            raise InputValidationError(
                "MangaDex: URL must point to /title/<uuid>",
                code="invalid_source_url",
            )
        value = (source_id or "").strip().strip("/")
        if value.startswith(("title/", "manga/")):
            value = value.split("/", 1)[1]
        if "/" in value:
            value = value.rsplit("/", 1)[-1]
        return self._ensure_uuid(value)

    def _resolve_chapter_id(self, source_id: str, url: str | None) -> str:
        if url:
            self.assert_allowed_url(url)
            segments = path_segments(url)
            if "chapter" in segments:
                index = segments.index("chapter")
                if index + 1 < len(segments):
                    return self._ensure_uuid(segments[index + 1])
            raise InputValidationError(
                "MangaDex: URL must point to /chapter/<uuid>",
                code="invalid_source_url",
            )
        value = (source_id or "").strip().strip("/")
        if value.startswith("chapter/"):
            value = value.split("/", 1)[1]
        if "/" in value:
            value = value.rsplit("/", 1)[-1]
        return self._ensure_uuid(value)

    @staticmethod
    def _ensure_uuid(value: str) -> str:
        try:
            return str(uuid.UUID(value))
        except (ValueError, AttributeError, TypeError) as exc:
            raise InputValidationError(
                "MangaDex: source_id must be a UUID",
                code="invalid_source_id",
            ) from exc
