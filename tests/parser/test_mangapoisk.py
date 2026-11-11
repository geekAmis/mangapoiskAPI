from __future__ import annotations

import copy

import httpx
import respx
from parser_helpers import (
    inertia_html,
    json_response,
    load_json,
    mock_allow_robots,
)
from services.parser.app.adapters.mangapoisk import MangaPoiskAdapter

HOME = load_json("mangapoisk_home.json")
SEARCH = load_json("mangapoisk_search.json")
MANGA = load_json("mangapoisk_manga.json")
CHAPTER = load_json("mangapoisk_chapter.json")
CHAPTER_EMPTY = load_json("mangapoisk_chapter_empty.json")

MANGA_PATH = "https://mangapoisk.me/manga/overgeared-abs3nSd"
CHAPTER_PATH = f"{MANGA_PATH}/chapter/1-300"
EMPTY_CHAPTER_PATH = f"{MANGA_PATH}/chapter/1-312"


async def test_search_parses_and_caches(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        mock_allow_robots(router, "mangapoisk.me")
        search_route = router.get("https://mangapoisk.me/search").mock(
            return_value=json_response(SEARCH)
        )
        adapter = MangaPoiskAdapter(client, settings, cache)

        result = await adapter.search("  Overgeared  ")

        assert result.source == "mangapoisk"
        assert result.page == 1
        assert result.total == 2
        assert len(result.items) == 2
        first = result.items[0]
        assert first.source_id == "overgeared-abs3nSd"
        assert first.slug == "overgeared-abs3nSd"
        assert "Во всеоружии" in first.title
        assert first.year == 2020
        assert first.url == MANGA_PATH
        assert first.poster_url is not None and first.poster_url.startswith("https://")
        assert search_route.calls[0].request.url.params["q"] == "Overgeared"

        cached = await adapter.search("overgeared")
        assert cached.total == 2
        assert search_route.call_count == 1


async def test_search_second_page_is_empty_without_request(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        search_route = router.get("https://mangapoisk.me/search").mock(
            return_value=json_response(SEARCH)
        )
        adapter = MangaPoiskAdapter(client, settings, cache)
        result = await adapter.search("overgeared", page=2)
        assert result.items == []
        assert result.has_next is False
        assert search_route.call_count == 0


async def test_manga_parses_inertia_payload(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        mock_allow_robots(router, "mangapoisk.me")
        home_route = router.get("https://mangapoisk.me/").mock(
            return_value=httpx.Response(200, text=inertia_html(HOME))
        )
        manga_route = router.get(MANGA_PATH).mock(return_value=json_response(MANGA))
        adapter = MangaPoiskAdapter(client, settings, cache)

        detail = await adapter.get_manga("overgeared-abs3nSd", chapters_limit=10)

        assert detail.source == "mangapoisk"
        assert detail.source_id == "overgeared-abs3nSd"
        assert detail.title == "Во всеоружии (перезапуск)"
        assert detail.title_en == "Overgeared"
        assert detail.year == 2020
        assert detail.rating == 4.15
        assert detail.rating_count == 402
        assert "фэнтези" in detail.genres
        assert detail.poster_url is not None
        assert detail.url == MANGA_PATH
        assert detail.latest_chapter is not None
        assert detail.latest_chapter.number == "312"
        numbers = [chapter.number for chapter in detail.chapters]
        assert numbers[:4] == ["312", "300", "299", "298"]
        assert "0" in numbers
        assert len(detail.chapters) == 5

        request = manga_route.calls[0].request
        assert request.headers["x-inertia"] == "true"
        assert request.headers["x-inertia-version"] == HOME["version"]
        assert home_route.call_count == 1

        cached = await adapter.get_manga("overgeared-abs3nSd", chapters_limit=10)
        assert cached.title == detail.title
        assert manga_route.call_count == 1


async def test_chapter_parses_pages_and_next_link(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        mock_allow_robots(router, "mangapoisk.me")
        router.get("https://mangapoisk.me/").mock(
            return_value=httpx.Response(200, text=inertia_html(HOME))
        )
        chapter_route = router.get(CHAPTER_PATH).mock(return_value=json_response(CHAPTER))
        adapter = MangaPoiskAdapter(client, settings, cache)

        detail = await adapter.get_chapter("overgeared-abs3nSd/1-300")

        assert detail.chapter.number == "300"
        assert detail.chapter.volume == "1"
        assert detail.chapter.title == "300 Том 1"
        assert len(detail.pages) == 3
        assert [page.number for page in detail.pages] == [1, 2, 3]
        assert detail.pages[0].url.startswith("https://static2.mangapoisk.me/pages/")
        assert detail.pages[0].width == 720
        assert detail.pages[0].height == 8390
        assert detail.next_url == f"{MANGA_PATH}/chapter/1-301"
        assert detail.prev_url is None
        assert detail.is_horizontal is False
        assert chapter_route.call_count == 1

        cached = await adapter.get_chapter("overgeared-abs3nSd/1-300")
        assert len(cached.pages) == 3
        assert chapter_route.call_count == 1


async def test_chapter_with_zero_pages_is_not_an_error(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        mock_allow_robots(router, "mangapoisk.me")
        router.get("https://mangapoisk.me/").mock(
            return_value=httpx.Response(200, text=inertia_html(HOME))
        )
        router.get(EMPTY_CHAPTER_PATH).mock(return_value=json_response(CHAPTER_EMPTY))
        adapter = MangaPoiskAdapter(client, settings, cache)

        detail = await adapter.get_chapter("overgeared-abs3nSd/1-312")

        assert detail.chapter.number == "312"
        assert detail.pages == []
        assert detail.next_url is None


async def test_inertia_409_refreshes_version(settings, cache, client) -> None:
    new_home = copy.deepcopy(HOME)
    new_home["version"] = "new-version-123"
    new_manga = copy.deepcopy(MANGA)
    new_manga["version"] = "new-version-123"
    manga_requests: list[httpx.Request] = []
    home_calls = {"count": 0}

    def home_handler(request: httpx.Request) -> httpx.Response:
        home_calls["count"] += 1
        payload = HOME if home_calls["count"] == 1 else new_home
        return httpx.Response(200, text=inertia_html(payload))

    def manga_handler(request: httpx.Request) -> httpx.Response:
        manga_requests.append(request)
        if len(manga_requests) == 1:
            return httpx.Response(409, headers={"X-Inertia-Location": MANGA_PATH})
        return json_response(new_manga)

    with respx.mock(assert_all_called=False) as router:
        mock_allow_robots(router, "mangapoisk.me")
        router.get("https://mangapoisk.me/").mock(side_effect=home_handler)
        router.get(MANGA_PATH).mock(side_effect=manga_handler)
        adapter = MangaPoiskAdapter(client, settings, cache)

        detail = await adapter.get_manga("overgeared-abs3nSd", chapters_limit=1)

        assert detail.title == "Во всеоружии (перезапуск)"
        assert home_calls["count"] == 2
        assert len(manga_requests) == 2
        assert manga_requests[0].headers["x-inertia-version"] == HOME["version"]
        assert manga_requests[1].headers["x-inertia-version"] == "new-version-123"


async def test_inertia_version_mismatch_refreshes(settings, cache, client) -> None:
    new_home = copy.deepcopy(HOME)
    new_home["version"] = "new-version-456"
    first_payload = copy.deepcopy(MANGA)
    first_payload["version"] = "new-version-456"
    second_payload = copy.deepcopy(MANGA)
    second_payload["version"] = "new-version-456"
    home_calls = {"count": 0}
    manga_calls = {"count": 0}

    def home_handler(request: httpx.Request) -> httpx.Response:
        home_calls["count"] += 1
        payload = HOME if home_calls["count"] == 1 else new_home
        return httpx.Response(200, text=inertia_html(payload))

    def manga_handler(request: httpx.Request) -> httpx.Response:
        manga_calls["count"] += 1
        return json_response(first_payload if manga_calls["count"] == 1 else second_payload)

    with respx.mock(assert_all_called=False) as router:
        mock_allow_robots(router, "mangapoisk.me")
        router.get("https://mangapoisk.me/").mock(side_effect=home_handler)
        router.get(MANGA_PATH).mock(side_effect=manga_handler)
        adapter = MangaPoiskAdapter(client, settings, cache)

        detail = await adapter.get_manga("overgeared-abs3nSd", chapters_limit=1)

        assert detail.title == "Во всеоружии (перезапуск)"
        assert home_calls["count"] == 2
        assert manga_calls["count"] == 2
