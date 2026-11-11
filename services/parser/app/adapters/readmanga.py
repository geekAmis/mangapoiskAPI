"""Conservative ReadManga HTML adapter.

The development network resets connections to ``readmanga.live``, so this
adapter is disabled by default and its selectors are validated with saved
fixtures only.  It intentionally uses a narrow set of stable-looking selectors
and never tries to work around anti-bot protection.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar
from urllib.parse import urlparse

from bs4 import Tag
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
from manga_common.text import parse_float, parse_int, parse_year

from .base import BaseAdapter
from .parsing import (
    absolute_url,
    chapter_numbers_from_text,
    first_text,
    normalize_number,
    path_segments,
)

_MANGA_PATH = "manga"
_CHAPTER_LINK_RE = re.compile(r"/chapter/|/manga/[^/]+/\d")
_PAGE_IMAGE_SELECTORS = (
    "img.page-image",
    ".page-image img",
    "img[data-page]",
    "#reader img",
    ".reader img",
    "div.reader img",
)
_CHAPTER_LINK_SELECTORS = (
    ".chapters a[href*='/manga/']",
    ".chapter-item a[href*='/manga/']",
    "tr.item a[href*='/manga/']",
    "div.chapter a[href*='/manga/']",
    "a[href*='/chapter/']",
)


def _card_year(text: str) -> int | None:
    return parse_year(text)


class ReadMangaAdapter(BaseAdapter):
    """HTML adapter for ``readmanga.live`` (disabled by default)."""

    info = SourceInfo(
        code="readmanga",
        name="ReadManga",
        base_url="https://readmanga.live",
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
            "Conservative HTML adapter. Network is unreachable from the development "
            "environment, so selectors are fixture-tested only."
        ),
    )
    allowed_hosts = frozenset({"readmanga.live", "www.readmanga.live"})
    max_concurrency = 1
    default_headers: ClassVar[dict[str, str]] = {"Accept": "text/html, application/xhtml+xml"}

    # ------------------------------------------------------------------
    # Mapping
    # ------------------------------------------------------------------

    def _chapter_from_link(
        self,
        href: str,
        text: str,
        *,
        default_slug: str = "",
    ) -> ChapterSummary | None:
        segments = path_segments(href)
        if _MANGA_PATH not in segments:
            return None
        index = segments.index(_MANGA_PATH)
        if index + 1 >= len(segments):
            return None
        slug = segments[index + 1] or default_slug
        if not slug:
            return None
        source_path = "/".join(segments[index:])
        rest = segments[index + 2 :]
        volume, number = chapter_numbers_from_text(text)
        if not number and rest:
            number = normalize_number(rest[-1])
        if not volume and len(rest) >= 2:
            candidate = normalize_number(rest[-2])
            if candidate.isdigit():
                volume = candidate
        number = number or "0"
        return ChapterSummary(
            source=self.info.code,
            source_id=source_path,
            manga_source_id=slug,
            volume=volume,
            number=number,
            title=first_text(text, f"Глава {number}"),
            page_count=0,
            url=absolute_url(self.info.base_url, href),
            is_external=False,
        )

    def _summary_from_card(self, card: Tag) -> MangaSummary | None:
        anchor = card.find("a", href=_CHAPTER_LINK_RE)
        manga_anchor = card.find("a", href=re.compile(r"/manga/"))
        if not isinstance(manga_anchor, Tag):
            return None
        href = first_text(manga_anchor.get("href"))
        segments = path_segments(href)
        if _MANGA_PATH not in segments:
            return None
        index = segments.index(_MANGA_PATH)
        if index + 1 >= len(segments):
            return None
        slug = segments[index + 1]
        title = first_text(
            manga_anchor.get("title"),
            _text(card.select_one(".element-title")),
            _text(card.select_one("h3")),
            manga_anchor.get_text(" ", strip=True),
            slug,
        )
        image = card.find("img")
        poster = first_text(
            image.get("data-src") if isinstance(image, Tag) else None,
            image.get("src") if isinstance(image, Tag) else None,
        )
        text = card.get_text(" ", strip=True)
        genres = [
            first_text(element.get_text(" ", strip=True))
            for element in card.select(".element-genre, a[href*='/genre/']")
        ]
        latest = None
        if isinstance(anchor, Tag):
            latest = self._chapter_from_link(
                first_text(anchor.get("href")),
                anchor.get_text(" ", strip=True),
                default_slug=slug,
            )
        return MangaSummary(
            source=self.info.code,
            source_id=slug,
            slug=slug,
            title=title,
            year=_card_year(text),
            rating=parse_float(_text(card.select_one(".rating"))),
            poster_url=absolute_url(self.info.base_url, poster),
            adult="18+" in text,
            genres=[genre for genre in genres if genre],
            url=absolute_url(self.info.base_url, href),
            latest_chapter=latest,
        )

    def _parse_cards(self, html: str) -> list[MangaSummary]:
        soup = self.parse_html(html)
        results: list[MangaSummary] = []
        seen: set[str] = set()
        for card in soup.select("div.element, div.tile, li.element"):
            summary = self._summary_from_card(card)
            if summary is None or summary.source_id in seen:
                continue
            seen.add(summary.source_id)
            results.append(summary)
        return results

    def _parse_manga_page(self, html: str, slug: str) -> MangaDetail:
        soup = self.parse_html(html)
        title = first_text(
            _text(soup.select_one("h1.manga-title")),
            _text(soup.select_one(".manga-title")),
            _text(soup.select_one("h1")),
        )
        description = first_text(
            _text(soup.select_one(".manga-description")),
            _text(soup.select_one("div.manga-description")),
        )
        poster = soup.select_one(".manga-poster img, .picture img, img[itemprop='image']")
        poster_url = None
        if isinstance(poster, Tag):
            poster_url = absolute_url(
                self.info.base_url,
                first_text(poster.get("data-src"), poster.get("src")),
            )
        genres = [
            first_text(element.get_text(" ", strip=True))
            for element in soup.select(".element-genre, a[href*='/genre/']")
        ]
        chapters: list[ChapterSummary] = []
        seen_chapters: set[str] = set()
        for selector in _CHAPTER_LINK_SELECTORS:
            for anchor in soup.select(selector):
                if not isinstance(anchor, Tag):
                    continue
                href = first_text(anchor.get("href"))
                chapter = self._chapter_from_link(
                    href,
                    anchor.get_text(" ", strip=True),
                    default_slug=slug,
                )
                if chapter is None or chapter.source_id in seen_chapters:
                    continue
                seen_chapters.add(chapter.source_id)
                chapters.append(chapter)
            if chapters:
                break
        if not title and not chapters:
            raise NotFoundError(
                "ReadManga: manga not found",
                code="not_found",
                details={"source": self.info.code, "source_id": slug},
            )
        text = soup.get_text(" ", strip=True)
        status = first_text(
            _text(soup.select_one(".manga-status")),
            _text(soup.select_one(".element-status")),
        )
        year = parse_year(first_text(_text(soup.select_one(".manga-year")))) or _card_year(text)
        summary = MangaSummary(
            source=self.info.code,
            source_id=slug,
            slug=slug,
            title=title or slug,
            description=description or None,
            year=year,
            status=status or None,
            rating=parse_float(_text(soup.select_one(".rating"))),
            poster_url=poster_url,
            adult="18+" in text or any("взросл" in genre.casefold() for genre in genres),
            genres=[genre for genre in genres if genre],
            url=absolute_url(self.info.base_url, f"/manga/{slug}"),
            latest_chapter=chapters[0] if chapters else None,
        )
        return MangaDetail(**summary.model_dump(), chapters=chapters)

    def _parse_chapter_page(
        self,
        html: str,
        *,
        path: str,
        manga_slug: str,
        chapter_source_id: str,
    ) -> ChapterDetail:
        soup = self.parse_html(html)
        pages: list[Page] = []
        seen: set[str] = set()
        for selector in _PAGE_IMAGE_SELECTORS:
            for image in soup.select(selector):
                if not isinstance(image, Tag):
                    continue
                source = first_text(
                    image.get("data-src"),
                    image.get("data-original"),
                    image.get("data-lazy-src"),
                    image.get("src"),
                )
                if not source or source.startswith(("data:", "about:", "javascript:")):
                    continue
                url = absolute_url(self.info.base_url, source)
                if not url or url in seen:
                    continue
                seen.add(url)
                pages.append(
                    Page(
                        number=len(pages) + 1,
                        url=url,
                        width=parse_int(image.get("width")),
                        height=parse_int(image.get("height")),
                    )
                )
            if pages:
                break

        if not pages:
            raise UpstreamError(
                "ReadManga: no page images found; the reader selectors may have changed",
                code="pages_unavailable",
                details={"source": self.info.code, "path": path},
            )

        title = first_text(
            _text(soup.select_one(".chapter-title")),
            _text(soup.select_one("h1")),
            f"Глава {chapter_source_id.rsplit('/', 1)[-1]}",
        )
        volume, number = chapter_numbers_from_text(title)
        if not number:
            number = chapter_source_id.rsplit("/", 1)[-1] or "0"
        if not volume:
            parts = chapter_source_id.strip("/").split("/")
            if len(parts) >= 2:
                candidate = parts[-2]
                if candidate.isdigit():
                    volume = candidate
        chapter = ChapterSummary(
            source=self.info.code,
            source_id=chapter_source_id,
            manga_source_id=manga_slug,
            volume=volume,
            number=number,
            title=title,
            page_count=len(pages),
            url=absolute_url(self.info.base_url, path),
            is_external=False,
        )
        return ChapterDetail(
            chapter=chapter,
            pages=pages,
            prev_url=_nav_link(soup, self.info.base_url, ("предыдущ", "назад", "prev")),
            next_url=_nav_link(soup, self.info.base_url, ("следующ", "вперёд", "вперед", "next")),
            is_horizontal=False,
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
        await self.ensure_robots_allowed("/search")
        html = await self.request_text("/search", params={"q": query, "page": page})
        soup = self.parse_html(html)
        items = self._parse_cards(html)
        has_next = soup.select_one("a[rel='next'], .pagination a.next") is not None
        result = SourceSearchResult(
            source=self.info.code,
            items=items,
            page=page,
            total=None,
            has_next=has_next,
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
        slug = self._resolve_manga(source_id, url)
        limit = self.clamp_chapters_limit(chapters_limit)
        cached = await self.cache_read_model("manga", (slug, limit), MangaDetail)
        if cached is not None:
            return cached
        await self.ensure_robots_allowed(f"/manga/{slug}")
        html = await self.request_text(f"/manga/{slug}")
        detail = self._parse_manga_page(html, slug)
        if limit:
            detail.chapters = detail.chapters[:limit]
        else:
            detail.chapters = []
        if detail.chapters:
            detail.latest_chapter = detail.chapters[0]
        await self.cache_write_model("manga", (slug, limit), detail)
        return detail

    async def get_chapter(
        self,
        source_id: str = "",
        *,
        url: str | None = None,
    ) -> ChapterDetail:
        path = self._resolve_chapter(source_id, url)
        segments = path_segments(path)
        if _MANGA_PATH not in segments or len(segments) < 3:
            raise InputValidationError(
                "ReadManga: chapter path must contain /manga/<slug>/<chapter>",
                code="invalid_source_id",
            )
        manga_index = segments.index(_MANGA_PATH)
        manga_slug = segments[manga_index + 1] if manga_index + 1 < len(segments) else ""
        chapter_source_id = "/".join(segments)
        cached = await self.cache_read_model(
            "chapter",
            (chapter_source_id,),
            ChapterDetail,
        )
        if cached is not None:
            return cached
        await self.ensure_robots_allowed(path)
        html = await self.request_text(path)
        detail = self._parse_chapter_page(
            html,
            path=path,
            manga_slug=manga_slug,
            chapter_source_id=chapter_source_id,
        )
        await self.cache_write_model("chapter", (chapter_source_id,), detail)
        return detail

    async def latest(self) -> SourceHome:
        # The home page layout was not verified from this network; a false
        # "latest" capability is more honest than emitting guessed cards.
        return SourceHome(source=self.info.code, popular=[], latest=[])

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
                "ReadManga: URL must point to /manga/<slug>",
                code="invalid_source_url",
            )
        value = (source_id or "").strip().strip("/")
        if value.startswith(f"{_MANGA_PATH}/"):
            value = value[len(_MANGA_PATH) + 1 :]
        if "/" in value:
            value = value.split("/", 1)[0]
        if not value:
            raise InputValidationError(
                "ReadManga: source_id or url is required",
                code="missing_source_id",
            )
        return value

    def _resolve_chapter(self, source_id: str, url: str | None) -> str:
        if url:
            self.assert_allowed_url(url)
            parsed = urlparse(url)
            return parsed.path or "/"
        value = (source_id or "").strip()
        if value.startswith(("http://", "https://")):
            self.assert_allowed_url(value)
            return urlparse(value).path or "/"
        if value.startswith("/"):
            return value
        if value.startswith(f"{_MANGA_PATH}/"):
            return f"/{value}"
        if "/" in value:
            return f"/{_MANGA_PATH}/{value}"
        raise InputValidationError(
            "ReadManga: source_id must be a /manga/<slug>/<chapter> path or a url must be provided",
            code="invalid_source_id",
        )


def _text(element: Tag | None) -> str:
    if element is None:
        return ""
    return element.get_text(" ", strip=True)


def _nav_link(soup: Any, base_url: str, words: tuple[str, ...]) -> str | None:
    for anchor in soup.find_all("a", href=True):
        label = anchor.get_text(" ", strip=True).casefold()
        rel = " ".join(anchor.get("rel") or []).casefold()
        if any(word in label for word in words) or any(word in rel for word in words):
            return absolute_url(base_url, anchor.get("href"))
    return None
