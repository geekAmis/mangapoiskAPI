from __future__ import annotations

import copy

import pytest
import respx
from manga_common.errors import UpstreamError
from parser_helpers import json_response, load_json
from services.parser.app.adapters.remanga import RemangaAdapter

API = "https://api.remanga.org"
SEARCH = load_json("remanga_search.json")
TITLE = load_json("remanga_title.json")
CHAPTERS = load_json("remanga_chapters.json")
CHAPTER = load_json("remanga_chapter.json")


async def test_search(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.get(f"{API}/api/v2/search/").mock(return_value=json_response(SEARCH))
        adapter = RemangaAdapter(client, settings, cache)

        result = await adapter.search("overgeared")

        assert result.source == "remanga"
        assert result.page == 1
        assert result.total == 2
        assert result.has_next is False
        first = result.items[0]
        assert first.source_id == "overgeared--"
        assert first.title == "Во всеоружии"
        assert first.title_en == "Overgeared (Пак Сэналь)"
        assert first.year == 2020
        assert first.rating == 8.8
        assert first.rating_count == 1768036
        assert first.status == "Продолжается"
        assert first.content_type == "Манхва"
        assert first.url == "https://remanga.org/manga/overgeared--"
        assert route.calls[0].request.url.params["query"] == "overgeared"

        cached = await adapter.search("overgeared")
        assert cached.items[0].source_id == "overgeared--"
        assert route.call_count == 1


async def test_manga_and_chapters(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        title_route = router.get(f"{API}/api/v2/titles/overgeared--/").mock(
            return_value=json_response(TITLE)
        )
        chapters_route = router.get(f"{API}/api/v2/titles/chapters/").mock(
            return_value=json_response(CHAPTERS)
        )
        adapter = RemangaAdapter(client, settings, cache)

        detail = await adapter.get_manga("overgeared--", chapters_limit=2)

        assert detail.source == "remanga"
        assert detail.source_id == "overgeared--"
        assert detail.title == "Во всеоружии"
        assert detail.title_en == "Overgeared (Пак Сэналь)"
        assert detail.year == 2020
        assert detail.rating == 8.8
        assert detail.adult is False
        assert "Экшен" in detail.genres
        assert detail.description is not None and "SATISFY" in detail.description
        assert detail.latest_chapter is not None
        assert detail.latest_chapter.number == "312"
        assert [chapter.number for chapter in detail.chapters] == ["312", "311"]
        assert detail.chapters[0].source_id == "2162890"
        assert detail.chapters[0].url is not None
        assert detail.chapters[0].url.endswith("/chapter/2162890")
        assert chapters_route.calls[0].request.url.params["branch_id"] == "9902"
        assert title_route.call_count == 1

        cached = await adapter.get_manga("overgeared--", chapters_limit=2)
        assert cached.title == detail.title
        assert title_route.call_count == 1


async def test_chapter_pages_and_neighbours(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.get(f"{API}/api/v2/titles/chapters/306290/").mock(
            return_value=json_response(CHAPTER)
        )
        adapter = RemangaAdapter(client, settings, cache)

        detail = await adapter.get_chapter("overgeared--/306290")

        assert detail.chapter.number == "3"
        assert detail.chapter.volume == "1"
        assert detail.chapter.page_count == 3
        assert len(detail.pages) == 3
        assert [page.number for page in detail.pages] == [1, 2, 3]
        assert detail.pages[0].url.startswith("https://img-reserve.reimg2.org/images/10308/1-3/")
        assert detail.pages[0].width == 728
        assert detail.prev_url == "https://remanga.org/manga/overgeared--/chapter/306283"
        assert detail.next_url is None
        assert route.call_count == 1

        cached = await adapter.get_chapter("overgeared--/306290")
        assert len(cached.pages) == 3
        assert route.call_count == 1


async def test_paid_chapter_is_rejected(settings, cache, client) -> None:
    paid = copy.deepcopy(CHAPTER)
    paid["is_paid"] = True
    paid["is_bought"] = False
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{API}/api/v2/titles/chapters/306290/").mock(
            return_value=json_response(paid)
        )
        adapter = RemangaAdapter(client, settings, cache)
        with pytest.raises(UpstreamError) as error:
            await adapter.get_chapter("overgeared--/306290")
        assert error.value.code == "chapter_paid"
        assert error.value.details["source"] == "remanga"


async def test_latest_is_empty_and_capability_false(settings, cache, client) -> None:
    adapter = RemangaAdapter(client, settings, cache)
    assert adapter.info.enabled is False
    assert adapter.info.capabilities.latest is False
    home = await adapter.latest()
    assert home.popular == []
    assert home.latest == []
