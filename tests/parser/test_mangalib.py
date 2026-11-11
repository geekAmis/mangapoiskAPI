from __future__ import annotations

import copy

import httpx
import pytest
import respx
from manga_common.errors import UpstreamError
from parser_helpers import json_response, load_json
from services.parser.app.adapters.mangalib import MangaLibAdapter

API = "https://api.imglib.info"
SEARCH = load_json("mangalib_search.json")
DETAIL = load_json("mangalib_detail.json")
CHAPTERS = load_json("mangalib_chapters.json")
CHAPTER = load_json("mangalib_chapter.json")
MANGA_ID = "6844--temppal"
CHAPTER_URL = f"https://mangalib.me/ru/manga/{MANGA_ID}/read/v1/c22?bid=490263"


async def test_search(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.get(f"{API}/api/manga").mock(return_value=json_response(SEARCH))
        adapter = MangaLibAdapter(client, settings, cache)

        result = await adapter.search("overgeared")

        assert result.source == "mangalib"
        assert result.page == 1
        assert result.has_next is False
        assert len(result.items) == 1
        item = result.items[0]
        assert item.source_id == MANGA_ID
        assert item.slug == "temppal"
        assert item.title == "Во всеоружии"
        assert item.title_en == "Overgeared"
        assert item.year == 2018
        assert item.rating == 8.6
        assert item.rating_count == 688
        assert item.content_type == "Манхва"
        assert item.url == f"https://mangalib.me/ru/manga/{MANGA_ID}"
        assert item.poster_url is not None
        request = route.calls[0].request
        assert request.url.params["q"] == "overgeared"
        assert request.url.params["page"] == "1"

        cached = await adapter.search("overgeared")
        assert cached.items[0].source_id == MANGA_ID
        assert route.call_count == 1


async def test_manga_uses_detail_endpoint_and_rus_name(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        detail_route = router.get(f"{API}/api/manga/{MANGA_ID}").mock(
            return_value=json_response(DETAIL)
        )
        chapters_route = router.get(f"{API}/api/manga/{MANGA_ID}/chapters").mock(
            return_value=json_response(CHAPTERS)
        )
        adapter = MangaLibAdapter(client, settings, cache)

        detail = await adapter.get_manga(MANGA_ID, chapters_limit=2)

        assert detail.source_id == MANGA_ID
        assert detail.title == "Во всеоружии"
        assert detail.title_en == "Overgeared"
        assert detail.latest_chapter is not None
        assert detail.latest_chapter.number == "22"
        assert [chapter.number for chapter in detail.chapters] == ["22", "21"]
        assert detail_route.call_count == 1
        assert chapters_route.call_count == 1
        assert detail_route.calls[0].request.headers["site-id"] == "1"


async def test_manga_falls_back_to_search_and_chapters(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        chapters_route = router.get(f"{API}/api/manga/{MANGA_ID}/chapters").mock(
            return_value=json_response(CHAPTERS)
        )
        router.get(f"{API}/api/manga/{MANGA_ID}").mock(
            return_value=httpx.Response(
                404,
                json={"data": {"toast": {"type": "silent", "message": "Not Found"}}},
            )
        )
        router.get(f"{API}/api/manga/temppal").mock(
            return_value=httpx.Response(
                404,
                json={"data": {"toast": {"type": "silent", "message": "Not Found"}}},
            )
        )
        search_route = router.get(f"{API}/api/manga").mock(
            return_value=json_response(SEARCH)
        )
        adapter = MangaLibAdapter(client, settings, cache)

        detail = await adapter.get_manga(MANGA_ID, chapters_limit=5)

        assert detail.source == "mangalib"
        assert detail.source_id == MANGA_ID
        assert detail.title == "Во всеоружии"
        assert detail.latest_chapter is not None
        assert detail.latest_chapter.number == "22"
        assert [chapter.number for chapter in detail.chapters] == [
            "22",
            "21",
            "20",
            "19",
            "18",
        ]
        assert detail.chapters[0].url is not None
        assert detail.chapters[0].url.startswith(
            f"https://mangalib.me/ru/manga/{MANGA_ID}/read/v1/c22"
        )
        assert search_route.call_count == 1
        assert chapters_route.call_count == 1

        cached = await adapter.get_manga(MANGA_ID, chapters_limit=5)
        assert cached.title == detail.title
        assert chapters_route.call_count == 1


async def test_get_chapter_pages_from_url(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.get(
            f"{API}/api/manga/{MANGA_ID}/chapter",
            params={"volume": "1", "number": "22"},
        ).mock(return_value=json_response(CHAPTER))
        adapter = MangaLibAdapter(client, settings, cache)

        detail = await adapter.get_chapter(url=CHAPTER_URL)

        assert detail.chapter.number == "22"
        assert detail.chapter.volume == "1"
        assert detail.chapter.page_count == 7
        assert detail.chapter.url == CHAPTER_URL
        assert detail.chapter.published_at is not None
        assert detail.is_horizontal is False
        assert detail.prev_url is None
        assert detail.next_url is None
        assert len(detail.pages) == 7
        first = detail.pages[0]
        assert first.number == 1
        assert first.url == (
            "https://img3.cdnlibs.org/manga/temppal/chapters/490263/001_F4tO.png"
        )
        assert first.width == 720
        assert first.height == 7686
        assert detail.pages[1].url == (
            "https://img3.cdnlibs.org/manga/temppal/chapters/490263/002_vMvc.png"
        )
        assert detail.pages[1].height == 4392
        request = route.calls[0].request
        assert request.url.params["volume"] == "1"
        assert request.url.params["number"] == "22"
        assert request.headers["origin"] == "https://mangalib.me"
        assert request.headers["referer"] == "https://mangalib.me/"
        assert request.headers["site-id"] == "1"

        cached = await adapter.get_chapter(url=CHAPTER_URL)
        assert len(cached.pages) == 7
        assert route.call_count == 1


def test_page_url_rewrites_old_img2_host(settings, cache, client) -> None:
    adapter = MangaLibAdapter(client, settings, cache)
    assert adapter._page_url(
        "https://img2.imglib.info/manga/example/chapters/1/page.png"
    ) == "https://img3.cdnlibs.org/manga/example/chapters/1/page.png"
    assert adapter._page_url(
        "//manga/example/chapters/1/page.png"
    ) == "https://img3.cdnlibs.org/manga/example/chapters/1/page.png"


async def test_get_chapter_accepts_composite_source_id(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.get(
            f"{API}/api/manga/{MANGA_ID}/chapter",
            params={"volume": "1", "number": "22"},
        ).mock(return_value=json_response(CHAPTER))
        adapter = MangaLibAdapter(client, settings, cache)

        detail = await adapter.get_chapter(f"{MANGA_ID}/1-22")

        assert detail.chapter.number == "22"
        assert len(detail.pages) == 7
        assert route.call_count == 1


async def test_get_chapter_reads_optional_neighbour_links(settings, cache, client) -> None:
    linked = copy.deepcopy(CHAPTER)
    linked["data"]["previous"] = {"volume": "1", "number": "21"}
    linked["data"]["next"] = {"volume": "1", "number": "23"}
    with respx.mock(assert_all_called=False) as router:
        router.get(
            f"{API}/api/manga/{MANGA_ID}/chapter",
            params={"volume": "1", "number": "22"},
        ).mock(return_value=json_response(linked))
        adapter = MangaLibAdapter(client, settings, cache)

        detail = await adapter.get_chapter(url=CHAPTER_URL)

        assert detail.prev_url == (
            f"https://mangalib.me/ru/manga/{MANGA_ID}/read/v1/c21"
        )
        assert detail.next_url == (
            f"https://mangalib.me/ru/manga/{MANGA_ID}/read/v1/c23"
        )


async def test_get_chapter_requires_slug_for_numeric_id(settings, cache, client) -> None:
    adapter = MangaLibAdapter(client, settings, cache)
    with pytest.raises(UpstreamError) as error:
        await adapter.get_chapter("490263")
    assert error.value.code == "chapter_identity_required"
    assert "full chapter URL" in error.value.message


async def test_get_chapter_without_pages_is_typed_error(settings, cache, client) -> None:
    empty = copy.deepcopy(CHAPTER)
    empty["data"]["pages"] = []
    with respx.mock(assert_all_called=False) as router:
        router.get(
            f"{API}/api/manga/{MANGA_ID}/chapter",
            params={"volume": "1", "number": "22"},
        ).mock(return_value=json_response(empty))
        adapter = MangaLibAdapter(client, settings, cache)
        with pytest.raises(UpstreamError) as error:
            await adapter.get_chapter(url=CHAPTER_URL)
        assert error.value.code == "pages_unavailable"
        assert error.value.details["slug_url"] == MANGA_ID


async def test_latest_uses_two_catalogue_sorts(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.get(f"{API}/api/manga").mock(return_value=json_response(SEARCH))
        adapter = MangaLibAdapter(client, settings, cache)

        home = await adapter.latest()

        assert home.source == "mangalib"
        assert len(home.popular) == 1
        assert len(home.latest) == 1
        assert route.call_count == 2
        sorts = [call.request.url.params.get("sort_by") for call in route.calls]
        assert None in sorts
        assert "last_chapter_at" in sorts
