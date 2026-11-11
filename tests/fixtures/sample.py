from __future__ import annotations

from datetime import UTC, datetime, timedelta

from manga_common.source_models import (
    ChapterDetail,
    ChapterSummary,
    MangaDetail,
    MangaSummary,
    Page,
    SourceCapabilities,
    SourceInfo,
    SourceSearchResult,
)


def sample_source() -> SourceInfo:
    return SourceInfo(
        code="mangapoisk",
        name="MangaPoisk",
        base_url="https://mangapoisk.me",
        capabilities=SourceCapabilities(
            search=True, catalog=True, manga=True, chapters=True, pages=True, latest=True
        ),
    )


def sample_chapter(number: str = "1", volume: str = "1") -> ChapterSummary:
    return ChapterSummary(
        source="mangapoisk",
        source_id=f"{volume}-{number}",
        manga_source_id="sample-manga",
        volume=volume,
        number=number,
        title=f"Глава {number}",
        published_at=datetime.now(UTC) - timedelta(days=1),
        page_count=3,
        url=f"https://mangapoisk.me/manga/sample-manga/chapter/{volume}-{number}",
    )


def sample_manga(chapters: int = 3) -> MangaDetail:
    chapter_list = [sample_chapter(str(i), "1") for i in range(1, chapters + 1)]
    return MangaDetail(
        source="mangapoisk",
        source_id="sample-manga",
        slug="sample-manga",
        title="Пример манги",
        title_en="Sample Manga",
        title_alt="サンプル",
        description="Описание тестовой манги.",
        year=2024,
        status="Продолжается",
        content_type="Манга",
        rating=8.7,
        rating_count=1234,
        poster_url="https://static2.mangapoisk.me/posters/1/cover.jpg",
        adult=False,
        genres=["фэнтези", "приключения"],
        url="https://mangapoisk.me/manga/sample-manga",
        chapters=chapter_list,
    )


def sample_search() -> SourceSearchResult:
    return SourceSearchResult(
        source="mangapoisk",
        items=[
            MangaSummary(
                source="mangapoisk",
                source_id="sample-manga",
                slug="sample-manga",
                title="Пример манги",
                poster_url="https://static2.mangapoisk.me/posters/1/cover.jpg",
                rating=8.7,
                rating_count=1234,
                genres=["фэнтези"],
                url="https://mangapoisk.me/manga/sample-manga",
            )
        ],
        page=1,
        total=1,
        has_next=False,
    )


def sample_chapter_detail() -> ChapterDetail:
    return ChapterDetail(
        chapter=sample_chapter("1", "1"),
        pages=[
            Page(
                number=i,
                url=f"https://static2.mangapoisk.me/pages/1/1/{i}.jpg",
                width=690,
                height=1000,
            )
            for i in range(1, 4)
        ],
    )
