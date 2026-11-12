from __future__ import annotations

import copy
import json
import os

import pytest
import respx
from fastapi.testclient import TestClient
from manga_common.config import Settings
from manga_common.errors import UpstreamError, ValidationError
from parser_helpers import json_response, load_json
from services.parser.app.adapters.remanga import RemangaAdapter
from services.parser.app.cookie_store import SourceCookieStore
from services.parser.app.main import create_app
from services.parser.app.settings import ParserSettings

API = "https://api.remanga.org"
SEARCH = load_json("remanga_search.json")
SEARCH_PAGE1 = load_json("remanga_search_page1.json")
SEARCH_PAGE2 = load_json("remanga_search_page2.json")
CATALOG = load_json("remanga_catalog.json")
CATALOG_PAGE2 = load_json("remanga_catalog_page2.json")
TITLE = load_json("remanga_title.json")
CHAPTERS = load_json("remanga_chapters.json")
CHAPTERS_PAGE2 = load_json("remanga_chapters_page2.json")
CHAPTER = load_json("remanga_chapter.json")
CHAPTER_BOUGHT = load_json("remanga_chapter_bought.json")
CHAPTER_FREE_TODAY = load_json("remanga_chapter_free_today.json")
PAID = load_json("remanga_chapter_paid.json")

TOKEN_HEADERS = {"X-Internal-Token": "test-internal-token"}


def _settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "environment": "test",
        "service_name": "parser-test",
        "log_json": False,
        "log_level": "WARNING",
        "internal_token": "test-internal-token",
        "scraper_requests_per_minute": 100_000,
        "scraper_cache_ttl_seconds": 60,
        "scraper_max_retries": 0,
        "http_timeout_seconds": 5.0,
    }
    values.update(overrides)
    return Settings(**values)


def _clear_cookie_env(monkeypatch) -> None:
    for name in (
        "REMANGA_COOKIE",
        "REMANGACOOKIE",
        "REMAGA_COOKIE",
        "REManga_COOKIE",
    ):
        monkeypatch.delenv(name, raising=False)


def _parser_settings(**overrides) -> ParserSettings:
    values = {
        "_env_file": None,
        "environment": "test",
        "service_name": "parser-test",
        "log_json": False,
        "log_level": "WARNING",
        "internal_token": "test-internal-token",
        "scraper_requests_per_minute": 100_000,
        "scraper_cache_ttl_seconds": 60,
        "scraper_max_retries": 0,
        "http_timeout_seconds": 5.0,
        "remanga_cookie": "",
    }
    values.update(overrides)
    return ParserSettings(**values)


async def test_search_maps_fields_and_caches(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.get(f"{API}/api/v2/search/").mock(return_value=json_response(SEARCH))
        adapter = RemangaAdapter(client, settings, cache)

        result = await adapter.search("overgeared")

        assert result.source == "remanga"
        assert result.page == 1
        assert result.total == 2
        assert result.total_pages == 1
        assert result.per_page == 20
        assert result.has_next is False
        first = result.items[0]
        assert first.chapters_count == 313
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
        assert request.headers["x-client-name"] == "web"
        assert "authorization" not in request.headers
        assert "cookie" not in request.headers

        cached = await adapter.search("overgeared")
        assert cached.items[0].source_id == "overgeared--"
        assert route.call_count == 1


async def test_search_sends_bearer_token_not_cookie(settings, cache, client) -> None:
    credentialed = settings.model_copy(update={"remanga_cookie": "auth:token=test-secret"})
    with respx.mock(assert_all_called=False) as router:
        route = router.get(f"{API}/api/v2/search/").mock(return_value=json_response(SEARCH))
        adapter = RemangaAdapter(client, credentialed, cache)

        assert adapter.cookie_configured is True
        assert adapter.cookie_mode == "bearer"
        await adapter.search("overgeared")

        request = route.calls[0].request
        assert request.headers["authorization"] == "Bearer test-secret"
        assert "cookie" not in request.headers


@pytest.mark.parametrize(
    ("raw", "token", "cookie_header"),
    [
        ("Bearer test-secret", "test-secret", None),
        ("Authorization: Bearer test-secret", "test-secret", None),
        ("test-secret", "test-secret", None),
        ("auth:token=test-secret", "test-secret", None),
        ("auth:server-token=test-secret", "test-secret", None),
        (
            "__ddg1_=abc; auth:token=test-secret; consent:cookie=1",
            "test-secret",
            None,
        ),
        ("__ddg1_=abc; __ddg2_=def", None, "__ddg1_=abc; __ddg2_=def"),
        ("Cookie: __ddg1_=abc", None, "__ddg1_=abc"),
        ("session=abc", None, "session=abc"),
        ('{"cookie": "auth:token=test-secret"}', "test-secret", None),
    ],
)
def test_credential_parsing(raw: str, token: str | None, cookie_header: str | None) -> None:
    from services.parser.app.adapters.remanga import _parse_credentials

    assert _parse_credentials(raw) == (token, cookie_header)
    assert _parse_credentials("") == (None, None)
    assert _parse_credentials(None) == (None, None)


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


async def test_catalogue_pages_and_mapping(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        page1_route = router.get(
            f"{API}/api/v2/search/catalog/",
            params={
                "page": 1,
                "count": 30,
                "ordering": "-rating",
                "unstrict_search_fields": "categories",
            },
        ).mock(return_value=json_response(CATALOG))
        page2_route = router.get(
            f"{API}/api/v2/search/catalog/",
            params={
                "page": 2,
                "count": 30,
                "ordering": "-rating",
                "unstrict_search_fields": "categories",
            },
        ).mock(return_value=json_response(CATALOG_PAGE2))
        adapter = RemangaAdapter(client, settings, cache)

        first = await adapter.catalogue(1)
        second = await adapter.catalogue(2)

        assert first.source == "remanga"
        assert first.page == 1
        assert first.has_next is True
        assert len(first.items) == 3
        assert first.items[0].source_id == "limit"
        assert first.items[0].title == "Лимит"
        assert first.per_page == 30
        assert "Драма" in first.items[0].genres
        assert "Криминал" in first.items[2].genres
        assert first.items[0].poster_url is not None
        assert second.page == 2
        assert second.has_next is False
        assert len(second.items) == 2
        assert page1_route.call_count == 1
        assert page2_route.call_count == 1

        cached = await adapter.catalogue(1)
        assert cached.items[0].source_id == "limit"
        assert page1_route.call_count == 1


async def test_catalogue_rejects_unsupported_ordering(settings, cache, client) -> None:
    adapter = RemangaAdapter(client, settings, cache)
    with pytest.raises(ValidationError) as error:
        await adapter.catalogue(1, ordering="; drop table")
    assert error.value.code == "invalid_ordering"


async def test_latest_uses_popular_and_newest_catalogue_pages(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        rating_route = router.get(
            f"{API}/api/v2/search/catalog/",
            params={
                "page": 1,
                "count": 30,
                "ordering": "-rating",
                "unstrict_search_fields": "categories",
            },
        ).mock(return_value=json_response(CATALOG))
        newest_route = router.get(
            f"{API}/api/v2/search/catalog/",
            params={
                "page": 1,
                "count": 30,
                "ordering": "-id",
                "unstrict_search_fields": "categories",
            },
        ).mock(return_value=json_response(CATALOG_PAGE2))
        adapter = RemangaAdapter(client, settings, cache)

        home = await adapter.latest()

        assert home.source == "remanga"
        assert len(home.popular) == 3
        assert len(home.latest) == 2
        assert home.popular[0].source_id == "limit"
        assert home.latest[0].source_id == "professor-layton-and-the-cheerful-mystery"
        assert rating_route.call_count == 1
        assert newest_route.call_count == 1

        cached = await adapter.latest()
        assert cached.popular[0].source_id == "limit"
        assert rating_route.call_count == 1
        assert newest_route.call_count == 1


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
        assert detail.chapters_count == 313
        assert detail.year == 2020
        assert detail.status == "Продолжается"
        assert detail.content_type == "Манхва"
        assert detail.rating == 8.8
        assert detail.rating_count == 1768039
        assert detail.adult is False
        assert "Экшен" in detail.genres
        assert "Веб" in detail.genres
        assert detail.authors == ["Пак Сэналь"]
        assert detail.artists == ["Художник Тестовый"]
        assert detail.description is not None and "SATISFY" in detail.description
        assert detail.poster_url == (
            "https://remanga.org/media/titles/overgeared--/cover_cb03dd26a8654ee7.webp"
        )
        assert detail.url == "https://remanga.org/manga/overgeared--"
        assert detail.latest_chapter is not None
        assert detail.latest_chapter.number == "311"
        # 312 is paid and not bought; 311 was bought; 310 is free today;
        # 309 is free; 308 (next page) is free.
        assert [chapter.number for chapter in detail.chapters] == ["311", "310", "309", "308"]
        assert [chapter.volume for chapter in detail.chapters] == ["1", "1", "1", "1"]
        assert detail.chapters[0].source_id == "2162889"
        assert detail.chapters[0].translator == "Litres MS"
        assert detail.chapters[0].page_count == 0
        assert detail.chapters[0].published_at is not None
        assert detail.chapters[0].url == "https://remanga.org/manga/overgeared--/2162889"
        assert title_route.call_count == 1
        assert chapters_route.call_count == 2
        for call, expected_page in zip(chapters_route.calls, ("1", "2"), strict=True):
            params = call.request.url.params
            assert params["branch_id"] == "9902"
            assert params["ordering"] == "-index"
            assert params["user_data"] == "1"
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


async def test_purchased_chapter_is_readable(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.get(f"{API}/api/v2/titles/chapters/2162891/").mock(
            return_value=json_response(CHAPTER_BOUGHT)
        )
        adapter = RemangaAdapter(client, settings, cache)

        detail = await adapter.get_chapter("overgeared--/2162891")

        assert detail.chapter.number == "4"
        assert detail.chapter.page_count == 31
        assert len(detail.pages) == 31
        assert route.call_count == 1


async def test_free_today_chapter_is_readable(settings, cache, client) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.get(f"{API}/api/v2/titles/chapters/2162892/").mock(
            return_value=json_response(CHAPTER_FREE_TODAY)
        )
        adapter = RemangaAdapter(client, settings, cache)

        detail = await adapter.get_chapter("overgeared--/2162892")

        assert detail.chapter.number == "5"
        assert len(detail.pages) == 31
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
        assert error.value.details["available"] is False
        assert error.value.details["reason"] == "paid_locked"
        assert "authorization" not in route.calls[0].request.headers


async def test_unpublished_chapter_is_rejected(settings, cache, client) -> None:
    unpublished = copy.deepcopy(CHAPTER)
    unpublished["is_published"] = False
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{API}/api/v2/titles/chapters/306290/").mock(
            return_value=json_response(unpublished)
        )
        adapter = RemangaAdapter(client, settings, cache)

        with pytest.raises(UpstreamError) as error:
            await adapter.get_chapter("overgeared--/306290")

        assert error.value.code == "chapter_unpublished"
        assert error.value.details["available"] is False
        assert error.value.details["reason"] == "unpublished"


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
        assert error.value.details["available"] is False


def test_chapter_access_flags(settings, cache, client) -> None:
    adapter = RemangaAdapter(client, settings, cache)
    assert adapter._chapter_access({"is_paid": False}) == "free"
    assert adapter._chapter_access({"is_paid": True, "is_bought": True}) == "purchased"
    assert adapter._chapter_access({"is_paid": True, "is_free_today": True}) == "free_today"
    assert adapter._chapter_access({"is_paid": True, "is_bought": False}) == "locked"
    assert adapter._chapter_access({"is_published": False}) == "unpublished"
    assert adapter._chapter_available({"is_paid": True, "is_bought": True}) is True
    assert adapter._chapter_available({"is_paid": True}) is False


def test_numeric_title_id_is_rejected(settings, cache, client) -> None:
    adapter = RemangaAdapter(client, settings, cache)
    with pytest.raises(ValidationError) as error:
        # The method is async; this test only exercises the synchronous parser.
        adapter._resolve_manga("10106", None)
    assert error.value.code == "invalid_source_id"


def test_capabilities_and_latest(settings, cache, client) -> None:
    adapter = RemangaAdapter(client, settings, cache)
    capabilities = adapter.info.capabilities
    assert adapter.info.enabled is True
    assert adapter.info.requires_cookies is True
    assert capabilities.search is True
    assert capabilities.catalog is True
    assert capabilities.manga is True
    assert capabilities.chapters is True
    assert capabilities.pages is True
    assert capabilities.latest is True
    assert capabilities.requires_auth_for_pages is False
    assert "Authorization: Bearer" in (adapter.info.notes or "")


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


def test_cookie_store_persists_atomically(tmp_path) -> None:
    path = tmp_path / "nested" / "source-cookies.json"
    store = SourceCookieStore(path)
    store.load()
    assert store.get("remanga") is None
    record = store.set_sync("remanga", "auth:token=test-secret")
    assert record is not None
    assert store.get("remanga") is not None
    assert path.exists()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["sources"]["remanga"]["cookie"] == "auth:token=test-secret"
    if os.name != "nt":
        assert (path.stat().st_mode & 0o777) == 0o600

    reloaded = SourceCookieStore(path)
    reloaded.load()
    assert reloaded.get("remanga") is not None
    assert reloaded.status("remanga")["configured"] is True


def test_cookie_store_seeds_environment_when_empty(tmp_path) -> None:
    path = tmp_path / "source-cookies.json"
    store = SourceCookieStore(path)
    store.load()
    seeded = store.seed_from_environment(
        _settings(remanga_cookie=None),
        environ={"REMANGACOOKIE": "env-secret"},
    )
    assert seeded == ["remanga"]
    assert store.status("remanga")["configured"] is True

    reloaded = SourceCookieStore(path)
    reloaded.load()
    assert reloaded.status("remanga")["configured"] is True
    assert reloaded.seed_from_environment(_settings(), environ={}) == []


def test_cookie_endpoints_require_token_and_store_runtime_value(tmp_path, monkeypatch) -> None:
    _clear_cookie_env(monkeypatch)
    store_path = tmp_path / "source-cookies.json"
    app = create_app(_parser_settings(parser_cookie_store_path=str(store_path)))
    with TestClient(app) as client:
        unauthorised = client.get("/internal/sources/remanga/cookie")
        assert unauthorised.status_code == 401

        unknown = client.get("/internal/sources/nope/cookie", headers=TOKEN_HEADERS)
        assert unknown.status_code == 404
        assert unknown.json()["error"]["code"] == "source_not_found"

        initial = client.get("/internal/sources/remanga/cookie", headers=TOKEN_HEADERS)
        assert initial.status_code == 200
        assert initial.json()["configured"] is False
        assert initial.json()["supported"] is True
        assert "test-secret" not in initial.text

        updated = client.put(
            "/internal/sources/remanga/cookie",
            json={"cookie": "auth:token=test-secret"},
            headers=TOKEN_HEADERS,
        )
        assert updated.status_code == 200
        assert updated.json()["configured"] is True
        assert "test-secret" not in updated.text
        assert store_path.exists()

        adapter = app.state.registry.get("remanga")
        assert adapter is not None
        assert adapter.cookie_configured is True
        assert adapter.cookie_mode == "bearer"

        current = client.get("/internal/sources/remanga/cookie", headers=TOKEN_HEADERS)
        assert current.status_code == 200
        assert current.json()["configured"] is True
        assert "test-secret" not in current.text

        cleared = client.put(
            "/internal/sources/remanga/cookie",
            json={"cookie": ""},
            headers=TOKEN_HEADERS,
        )
        assert cleared.status_code == 200
        assert cleared.json()["configured"] is False
        assert adapter.cookie_configured is False


def test_cookie_endpoint_restores_runtime_credential_after_restart(tmp_path, monkeypatch) -> None:
    _clear_cookie_env(monkeypatch)
    store_path = tmp_path / "source-cookies.json"
    first_app = create_app(_parser_settings(parser_cookie_store_path=str(store_path)))
    with TestClient(first_app) as client:
        response = client.put(
            "/internal/sources/remanga/cookie",
            json={"cookie": "test-secret"},
            headers=TOKEN_HEADERS,
        )
        assert response.status_code == 200
    assert store_path.exists()

    second_app = create_app(_parser_settings(parser_cookie_store_path=str(store_path)))
    with TestClient(second_app) as client:
        status_response = client.get(
            "/internal/sources/remanga/cookie", headers=TOKEN_HEADERS
        )
        assert status_response.status_code == 200
        assert status_response.json()["configured"] is True
        adapter = second_app.state.registry.get("remanga")
        assert adapter is not None
        assert adapter.cookie_configured is True


def test_remanga_is_enabled_and_catalog_capable_in_sources(tmp_path, monkeypatch) -> None:
    _clear_cookie_env(monkeypatch)
    app = create_app(_parser_settings(parser_cookie_store_path=str(tmp_path / "cookies.json")))
    with TestClient(app) as client:
        response = client.get("/internal/sources", headers=TOKEN_HEADERS)
        assert response.status_code == 200
        sources = {item["code"]: item for item in response.json()}
        remanga = sources["remanga"]
        assert remanga["enabled"] is True
        assert remanga["capabilities"]["catalog"] is True
        assert remanga["capabilities"]["search"] is True
        assert remanga["capabilities"]["latest"] is True
