from __future__ import annotations

import httpx
import respx
from parser_helpers import load_text, mock_allow_robots
from services.parser.app.adapters.readmanga import ReadMangaAdapter

BASE = "https://readmanga.live"
SEARCH_HTML = load_text("readmanga_search.html")
MANGA_HTML = load_text("readmanga_manga.html")
CHAPTER_HTML = load_text("readmanga_chapter.html")


async def test_search(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        mock_allow_robots(router, "readmanga.live")
        route = router.get(f"{BASE}/search").mock(
            return_value=httpx.Response(200, text=SEARCH_HTML)
        )
        adapter = ReadMangaAdapter(client, settings, cache)

        result = await adapter.search("overgeared")

        assert result.source == "readmanga"
        assert len(result.items) == 2
        assert result.has_next is True
        first = result.items[0]
        assert first.source_id == "overgeared"
        assert first.title == "Во всеоружии"
        assert first.year == 2020
        assert first.rating == 8.9
        assert "фэнтези" in first.genres
        assert first.latest_chapter is not None
        assert first.latest_chapter.number == "312"
        assert first.url == f"{BASE}/manga/overgeared/"
        assert first.poster_url == "https://img.readmanga.live/cover/overgeared.jpg"
        assert route.calls[0].request.url.params["q"] == "overgeared"


async def test_manga(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        mock_allow_robots(router, "readmanga.live")
        route = router.get(f"{BASE}/manga/overgeared").mock(
            return_value=httpx.Response(200, text=MANGA_HTML)
        )
        adapter = ReadMangaAdapter(client, settings, cache)

        detail = await adapter.get_manga("overgeared", chapters_limit=2)

        assert detail.source == "readmanga"
        assert detail.source_id == "overgeared"
        assert detail.title == "Во всеоружии"
        assert detail.year == 2020
        assert detail.status == "Продолжается"
        assert detail.rating == 8.9
        assert "фэнтези" in detail.genres
        assert detail.description is not None and "редкую книгу" in detail.description
        assert len(detail.chapters) == 2
        assert [chapter.number for chapter in detail.chapters] == ["312", "311"]
        assert detail.latest_chapter is not None
        assert detail.latest_chapter.number == "312"
        assert detail.chapters[0].source_id == "manga/overgeared/1/312"
        assert route.call_count == 1


async def test_chapter(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        mock_allow_robots(router, "readmanga.live")
        route = router.get(f"{BASE}/manga/overgeared/1/312").mock(
            return_value=httpx.Response(200, text=CHAPTER_HTML)
        )
        adapter = ReadMangaAdapter(client, settings, cache)

        detail = await adapter.get_chapter("manga/overgeared/1/312")

        assert detail.chapter.number == "312"
        assert detail.chapter.volume == "1"
        assert detail.chapter.page_count == 2
        assert [page.number for page in detail.pages] == [1, 2]
        assert detail.pages[0].width == 720
        assert detail.pages[0].height == 1024
        assert detail.pages[0].url == "https://img.readmanga.live/pages/overgeared/312/1.jpg"
        assert detail.pages[1].url == "https://img.readmanga.live/pages/overgeared/312/2.jpg"
        assert detail.prev_url == f"{BASE}/manga/overgeared/1/311"
        assert detail.next_url == f"{BASE}/manga/overgeared/1/313"
        assert route.call_count == 1
