from __future__ import annotations

import httpx
import pytest
import respx
from manga_common.errors import UpstreamError
from parser_helpers import json_response, load_json
from services.parser.app.adapters.hentailib import HentaiLibAdapter
from services.parser.app.settings import ParserSettings

API = "https://hapi.hentaicdn.org/api"
SITE = "https://hentailib.me"
MANGA_ID = "33052--adabana"
SEARCH = load_json("hentailib_search.json")
DETAIL = load_json("hentailib_detail.json")
CHAPTERS = load_json("hentailib_chapters.json")
CHAPTER = load_json("hentailib_chapter.json")


async def test_search_maps_adult_flags_and_cache(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.get(f"{API}/manga").mock(return_value=json_response(SEARCH))
        adapter = HentaiLibAdapter(client, settings, cache)

        result = await adapter.search("adabana")

        assert result.source == "hentailib"
        assert result.page == 1
        assert len(result.items) == 1
        item = result.items[0]
        assert item.source_id == MANGA_ID
        assert item.title == "Пустоцвет"
        assert item.adult is True
        assert item.adult_only is True
        assert item.requires_age_confirmation is True
        assert item.url == f"{SITE}/ru/manga/{MANGA_ID}"
        request = route.calls[0].request
        assert request.url.params["q"] == "adabana"
        assert request.url.params["site_id[]"] == "4"
        assert request.headers["site-id"] == "4"

        cached = await adapter.search("adabana")
        assert cached.items[0].source_id == MANGA_ID
        assert route.call_count == 1


async def test_detail_and_chapters(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{API}/manga/{MANGA_ID}").mock(return_value=json_response(DETAIL))
        router.get(f"{API}/manga/{MANGA_ID}/chapters").mock(
            return_value=json_response(CHAPTERS)
        )
        adapter = HentaiLibAdapter(client, settings, cache)

        detail = await adapter.get_manga(MANGA_ID, chapters_limit=10)

        assert detail.title == "Пустоцвет"
        assert detail.description == "Короткое описание тайтла."
        assert detail.adult_only is True
        assert detail.genres == ["Драма", "Ужасы"]
        assert [chapter.number for chapter in detail.chapters] == ["2", "1"]
        assert detail.chapters[0].url is not None
        assert "bid=25610" in (detail.chapters[0].url or "")
        assert detail.latest_chapter is not None
        assert detail.latest_chapter.number == "2"


async def test_reader_pages_normalise_protocol_relative_urls(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.get(f"{API}/manga/{MANGA_ID}/chapter").mock(
            return_value=json_response(CHAPTER)
        )
        adapter = HentaiLibAdapter(client, settings, cache)

        detail = await adapter.get_chapter(
            url=f"{SITE}/ru/manga/{MANGA_ID}/read/v1/c1"
        )

        assert len(detail.pages) == 2
        assert detail.pages[0].url == "https://img.hentaicdn.org/chapters/1/1.jpg"
        assert detail.pages[1].url == "https://img.hentaicdn.org/chapters/1/2.jpg"
        assert detail.chapter.page_count == 2
        assert detail.next_url is not None
        request = route.calls[0].request
        assert request.url.params["volume"] == "1"
        assert request.url.params["number"] == "1"


async def test_reader_404_is_typed_not_leaked(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{API}/manga/{MANGA_ID}/chapter").mock(
            return_value=httpx.Response(
                404, json={"data": {"toast": {"type": "silent", "message": "Not Found"}}}
            )
        )
        adapter = HentaiLibAdapter(client, settings, cache)

        with pytest.raises(UpstreamError) as error:
            await adapter.get_chapter(
                url=f"{SITE}/ru/manga/{MANGA_ID}/read/v1/c1"
            )
        assert error.value.code == "chapter_unavailable"
        assert "authenticated session" in error.value.message


async def test_api_host_fallback(cache, client) -> None:
    settings = ParserSettings(
        _env_file=None,
        environment="test",
        log_level="WARNING",
        log_json=False,
        internal_token="test-internal-token",
        scraper_requests_per_minute=100_000,
        scraper_cache_ttl_seconds=60,
        scraper_max_retries=0,
        http_timeout_seconds=5.0,
        hentailib_base_urls="https://broken.example,https://hentailib.me",
        hentailib_api_base_urls="https://broken.example/api,https://hapi.hentaicdn.org/api",
    )
    with respx.mock(assert_all_called=False) as router:
        router.get("https://broken.example/api/manga").mock(
            side_effect=httpx.ConnectError("blocked")
        )
        good = router.get(f"{API}/manga").mock(return_value=json_response(SEARCH))
        adapter = HentaiLibAdapter(client, settings, cache)

        result = await adapter.search("adabana")

        assert result.items[0].source_id == MANGA_ID
        assert good.call_count == 1
        assert adapter._active_api == API


async def test_fallback_domains_are_configurable(settings, cache, client) -> None:
    custom = ParserSettings(
        _env_file=None,
        environment="test",
        hentailib_base_urls="https://hentailib.me,https://mirror.example",
        hentailib_api_base_urls="https://hapi.hentaicdn.org/api",
    )
    adapter = HentaiLibAdapter(client, custom, cache)
    assert "hentailib.me" in adapter.allowed_hosts
    assert "mirror.example" in adapter.allowed_hosts
    assert "hapi.hentaicdn.org" in adapter.allowed_hosts
    assert adapter.max_concurrency == 1
    assert adapter.limiter.per_minute == custom.scraper_requests_per_minute
    assert adapter.cache_ttl == custom.scraper_cache_ttl_seconds
