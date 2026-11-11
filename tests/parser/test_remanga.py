from __future__ import annotations

import copy

import pytest
import respx
from manga_common.errors import UpstreamError, ValidationError
from parser_helpers import json_response, load_json
from services.parser.app.adapters.remanga import RemangaAdapter

API = "https://api.remanga.org"
SEARCH = load_json("remanga_search.json")
SEARCH_PAGE1 = load_json("remanga_search_page1.json")
SEARCH_PAGE2 = load_json("remanga_search_page2.json")
TITLE = load_json("remanga_title.json")
CHAPTERS = load_json("remanga_chapters.json")
CHAPTERS_PAGE2 = load_json("remanga_chapters_page2.json")
CHAPTER = load_json("remanga_chapter.json")
PAID = load_json("remanga_chapter_paid.json")


async def test_search_maps_fields_and_caches(settings, cache, client) -> None:
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
        assert first.slug == "overgeared--"
        assert first.title == "Во всеоружии"
        assert first.title_en == "Overgeared (Пак Сэналь)"
        assert first.year == 2020
        assert first.rating == 8.8
        assert first.rating_count == 1768039
        assert first.status == "Продолжается"
        assert first.content_type == "Манхва"
        assert first.adult is False
        assert first.poster_url == (
            "https://remanga.org/media/titles/overgeared--/cover_cb03dd26a8654ee7.webp"
        )
        assert first.url == "https://remanga.org/manga/overgeared--"
        request = route.calls[0].request
        assert request.url.params["query"] == "overgeared"
        assert request.url.params["page"] == "1"
        assert "application/json" in request.headers["accept"]
        assert request.headers["origin"] == "https://remanga.org"
        assert request.headers["referer"] == "https://remanga.org/"
        assert "authorization" not in request.headers

        cached = await adapter.search("overgeared")
        assert cached.items[0].source_id == "overgeared--"
        assert route.call_count == 1


async def test_search_pagination(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        page1_route = router.get(
            f"{API}/api/v2/search/", params={"query": "дракон", "page": 1}
        ).mock(return_value=json_response(SEARCH_PAGE1))
        page2_route = router.get(
            f"{API}/api/v2/search/", params={"query": "дракон", "page": 2}
        ).mock(return_value=json_response(SEARCH_PAGE2))
        adapter = RemangaAdapter(client, settings, cache)

        first = await adapter.search("дракон")
        second = await adapter.search("дракон", page=2)

        assert first.page == 1
        assert first.total == 582
        assert first.has_next is True
        assert first.items[0].source_id == "dragon-inside-me"
        assert second.page == 2
        assert second.has_next is True
        assert second.items[0].source_id == "dragon-emperor-vakyrie"
        assert page1_route.call_count == 1
        assert page2_route.call_count == 1


async def test_manga_detail_chapters_and_pagination(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        title_route = router.get(f"{API}/api/v2/titles/overgeared--/").mock(
            return_value=json_response(TITLE)
        )
        chapters_route = router.get(f"{API}/api/v2/titles/chapters/").mock(
            side_effect=[
                json_response(CHAPTERS),
                json_response(CHAPTERS_PAGE2),
            ]
        )
        adapter = RemangaAdapter(client, settings, cache)

        detail = await adapter.get_manga("overgeared--", chapters_limit=4)

        assert detail.source == "remanga"
        assert detail.source_id == "overgeared--"
        assert detail.title == "Во всеоружии"
        assert detail.title_en == "Overgeared (Пак Сэналь)"
        assert detail.year == 2020
        assert detail.status == "Продолжается"
        assert detail.content_type == "Манхва"
        assert detail.rating == 8.8
        assert detail.rating_count == 1768039
        assert detail.adult is False
        assert "Экшен" in detail.genres
        assert "Веб" in detail.genres
        assert detail.description is not None and "SATISFY" in detail.description
        assert detail.poster_url == (
            "https://remanga.org/media/titles/overgeared--/cover_cb03dd26a8654ee7.webp"
        )
        assert detail.url == "https://remanga.org/manga/overgeared--"
        assert detail.latest_chapter is not None
        assert detail.latest_chapter.number == "312"
        assert [chapter.number for chapter in detail.chapters] == ["312", "311", "310", "282"]
        assert [chapter.volume for chapter in detail.chapters] == ["1", "1", "1", "1"]
        assert detail.chapters[0].source_id == "2162890"
        assert detail.chapters[0].page_count == 0
        assert detail.chapters[0].published_at is not None
        assert detail.chapters[0].url == "https://remanga.org/manga/overgeared--/2162890"
        assert title_route.call_count == 1
        assert chapters_route.call_count == 2
        for call, expected_page in zip(chapters_route.calls, ("1", "2"), strict=True):
            params = call.request.url.params
            assert params["branch_id"] == "9902"
            assert params["ordering"] == "-index"
            assert params["page"] == expected_page

        cached = await adapter.get_manga("overgeared--", chapters_limit=4)
        assert cached.title == detail.title
        assert title_route.call_count == 1
        assert chapters_route.call_count == 2


async def test_manga_prefers_branch_with_most_chapters(settings, cache, client) -> None:
    branched = copy.deepcopy(TITLE)
    branched["branches"] = [
        {"id": 1, "count_chapters": 2, "publishers": []},
        *branched["branches"],
    ]
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{API}/api/v2/titles/overgeared--/").mock(
            return_value=json_response(branched)
        )
        chapters_route = router.get(f"{API}/api/v2/titles/chapters/").mock(
            return_value=json_response({"next": None, "previous": None, "results": []})
        )
        adapter = RemangaAdapter(client, settings, cache)

        detail = await adapter.get_manga("overgeared--", chapters_limit=1)

        assert detail.chapters == []
        assert chapters_route.calls[0].request.url.params["branch_id"] == "9902"


async def test_manga_accepts_site_url_and_zero_chapter_limit(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        title_route = router.get(f"{API}/api/v2/titles/overgeared--/").mock(
            return_value=json_response(TITLE)
        )
        adapter = RemangaAdapter(client, settings, cache)

        detail = await adapter.get_manga(
            url="https://remanga.org/manga/overgeared--/chapters",
            chapters_limit=0,
        )

        assert detail.source_id == "overgeared--"
        assert detail.chapters == []
        assert title_route.call_count == 1


async def test_chapter_pages_from_reader_url(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.get(f"{API}/api/v2/titles/chapters/306290/").mock(
            return_value=json_response(CHAPTER)
        )
        adapter = RemangaAdapter(client, settings, cache)

        detail = await adapter.get_chapter(
            url="https://remanga.org/manga/overgeared--/306290"
        )

        assert detail.chapter.source_id == "306290"
        assert detail.chapter.manga_source_id == "overgeared--"
        assert detail.chapter.number == "3"
        assert detail.chapter.volume == "1"
        assert detail.chapter.page_count == 31
        assert detail.chapter.url == "https://remanga.org/manga/overgeared--/306290"
        assert detail.chapter.published_at is not None
        assert len(detail.pages) == 31
        assert [page.number for page in detail.pages[:3]] == [1, 2, 3]
        assert detail.pages[0].url == (
            "https://img-reserve.reimg2.org/images/10308/1-3/"
            "a3fd83144c57bd506c68257cdead214c.jpeg"
        )
        assert detail.pages[0].width == 728
        assert detail.pages[0].height == 1189
        assert detail.prev_url == "https://remanga.org/manga/overgeared--/306283"
        assert detail.next_url is None
        assert detail.is_horizontal is False
        assert route.call_count == 1

        cached = await adapter.get_chapter("overgeared--/306290")
        assert len(cached.pages) == 31
        assert route.call_count == 1


async def test_chapter_accepts_legacy_and_api_urls(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.get(f"{API}/api/v2/titles/chapters/306290/").mock(
            return_value=json_response(CHAPTER)
        )
        adapter = RemangaAdapter(client, settings, cache)

        legacy = await adapter.get_chapter(
            url="https://remanga.org/manga/overgeared--/chapter/306290"
        )
        api_url = await adapter.get_chapter(
            url="https://api.remanga.org/api/v2/titles/chapters/306290/"
        )

        assert legacy.chapter.url == "https://remanga.org/manga/overgeared--/306290"
        assert api_url.chapter.manga_source_id == ""
        assert api_url.chapter.url == "https://api.remanga.org/api/v2/titles/chapters/306290/"
        assert route.call_count == 2


async def test_numeric_chapter_id_is_supported_without_title_url(
    settings, cache, client
) -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{API}/api/v2/titles/chapters/306290/").mock(
            return_value=json_response(CHAPTER)
        )
        adapter = RemangaAdapter(client, settings, cache)

        detail = await adapter.get_chapter("306290")

        assert detail.chapter.manga_source_id == ""
        assert detail.chapter.url is None
        assert detail.prev_url is None
        assert detail.next_url is None
        assert len(detail.pages) == 31


async def test_paid_chapter_is_rejected_with_typed_error(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.get(f"{API}/api/v2/titles/chapters/2162890/").mock(
            return_value=json_response(PAID)
        )
        adapter = RemangaAdapter(client, settings, cache)

        with pytest.raises(UpstreamError) as error:
            await adapter.get_chapter("https://remanga.org/manga/overgeared--/2162890")

        assert error.value.code == "chapter_paid"
        assert error.value.details["source"] == "remanga"
        assert error.value.details["chapter_id"] == 2162890
        assert error.value.details["title_id"] == 10106
        assert error.value.details["price"] == "10.00"
        assert "authorization" not in route.calls[0].request.headers


async def test_chapter_without_pages_is_typed_error(settings, cache, client) -> None:
    empty = copy.deepcopy(CHAPTER)
    empty["pages"] = []
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{API}/api/v2/titles/chapters/306290/").mock(
            return_value=json_response(empty)
        )
        adapter = RemangaAdapter(client, settings, cache)

        with pytest.raises(UpstreamError) as error:
            await adapter.get_chapter("overgeared--/306290")

        assert error.value.code == "pages_unavailable"
        assert error.value.details["chapter_id"] == 306290
        assert error.value.details["is_paid"] is False


async def test_numeric_title_id_is_rejected(settings, cache, client) -> None:
    adapter = RemangaAdapter(client, settings, cache)
    with pytest.raises(ValidationError) as error:
        await adapter.get_manga("10106")
    assert error.value.code == "invalid_source_id"


async def test_capabilities_and_latest(settings, cache, client) -> None:
    adapter = RemangaAdapter(client, settings, cache)
    capabilities = adapter.info.capabilities
    assert adapter.info.enabled is False
    assert capabilities.search is True
    assert capabilities.manga is True
    assert capabilities.chapters is True
    assert capabilities.pages is True
    assert capabilities.latest is False
    assert capabilities.requires_auth_for_pages is False
    assert "robots.txt" in (adapter.info.notes or "")

    home = await adapter.latest()
    assert home.popular == []
    assert home.latest == []


def test_reader_url_normalisation(settings, cache, client) -> None:
    adapter = RemangaAdapter(client, settings, cache)
    assert adapter._resolve_chapter(
        "", "https://remanga.org/manga/overgeared--/306290"
    ) == ("overgeared--", 306290)
    assert adapter._resolve_chapter(
        "", "https://remanga.org/manga/overgeared--/chapter/306290"
    ) == ("overgeared--", 306290)
    assert adapter._resolve_chapter("overgeared--/306290", None) == (
        "overgeared--",
        306290,
    )
    assert adapter._resolve_chapter("306290", None) == (None, 306290)
    assert adapter._resolve_manga(
        "", "https://remanga.org/manga/overgeared--/chapters"
    ) == "overgeared--"
