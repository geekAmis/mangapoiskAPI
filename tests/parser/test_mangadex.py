from __future__ import annotations

import respx
from parser_helpers import json_response, load_json
from services.parser.app.adapters.mangadex import MangaDexAdapter

API = "https://api.mangadex.org"
MANGA_ID = "123e4567-e89b-12d3-a456-426614174000"
CHAPTER_ID = "123e4567-e89b-12d3-a456-426614174001"
SEARCH = load_json("mangadex_search.json")
MANGA = load_json("mangadex_manga.json")
FEED = load_json("mangadex_feed.json")
CHAPTER = load_json("mangadex_chapter.json")
AT_HOME = load_json("mangadex_athome.json")


async def test_search(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.get(f"{API}/manga").mock(return_value=json_response(SEARCH))
        adapter = MangaDexAdapter(client, settings, cache)

        result = await adapter.search("overgeared")

        assert result.source == "mangadex"
        assert result.total == 1
        assert result.has_next is False
        item = result.items[0]
        assert item.source_id == MANGA_ID
        assert item.title == "Во всеоружии"
        assert item.title_en == "Overgeared"
        assert item.title_alt == "テムパル"
        assert item.year == 2020
        assert item.status == "ongoing"
        assert item.content_type == "manhwa"
        assert item.adult is False
        assert "Фэнтези" in item.genres
        assert item.poster_url == (
            f"https://uploads.mangadex.org/covers/{MANGA_ID}/cover.png.256.jpg"
        )
        assert route.calls[0].request.url.params["title"] == "overgeared"
        assert route.calls[0].request.url.params["translatedLanguage[]"] == "ru"

        cached = await adapter.search("overgeared")
        assert cached.total == 1
        assert route.call_count == 1


async def test_manga_and_feed(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        manga_route = router.get(f"{API}/manga/{MANGA_ID}").mock(
            return_value=json_response(MANGA)
        )
        feed_route = router.get(f"{API}/manga/{MANGA_ID}/feed").mock(
            return_value=json_response(FEED)
        )
        adapter = MangaDexAdapter(client, settings, cache)

        detail = await adapter.get_manga(MANGA_ID, chapters_limit=5)

        assert detail.source == "mangadex"
        assert detail.source_id == MANGA_ID
        assert detail.title == "Во всеоружии"
        assert len(detail.chapters) == 2
        assert detail.latest_chapter is not None
        assert detail.latest_chapter.number == "312"
        assert [chapter.number for chapter in detail.chapters] == ["312", "311"]
        assert detail.chapters[0].page_count == 2
        assert feed_route.calls[0].request.url.params["translatedLanguage[]"] == "ru"
        assert feed_route.calls[0].request.url.params["order[volume]"] == "desc"
        assert manga_route.call_count == 1

        cached = await adapter.get_manga(MANGA_ID, chapters_limit=5)
        assert cached.title == detail.title
        assert feed_route.call_count == 1


async def test_chapter_pages(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        chapter_route = router.get(f"{API}/chapter/{CHAPTER_ID}").mock(
            return_value=json_response(CHAPTER)
        )
        at_home_route = router.get(f"{API}/at-home/server/{CHAPTER_ID}").mock(
            return_value=json_response(AT_HOME)
        )
        adapter = MangaDexAdapter(client, settings, cache)

        detail = await adapter.get_chapter(url=f"https://mangadex.org/chapter/{CHAPTER_ID}")

        assert detail.chapter.number == "312"
        assert detail.chapter.volume == "1"
        assert detail.chapter.page_count == 2
        assert [page.number for page in detail.pages] == [1, 2]
        assert detail.pages[0].url == "https://uploads.mangadex.org/data/abc123hash/p1-1.png"
        assert detail.pages[1].url == "https://uploads.mangadex.org/data/abc123hash/p1-2.png"
        assert detail.chapter.manga_source_id == MANGA_ID
        assert chapter_route.call_count == 1
        assert at_home_route.call_count == 1


async def test_disabled_by_default(settings, cache, client) -> None:
    adapter = MangaDexAdapter(client, settings, cache)
    assert adapter.info.enabled is False
    assert adapter.info.capabilities.pages is True
    home = await adapter.latest()
    assert home.popular == []
