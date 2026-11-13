from __future__ import annotations

import html
import json
import re
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from services.gateway.app import prerender

MANGA_ID = "23d337ac-d72d-4fd6-9cda-e314d72ddafd"
CHAPTER_ID = "11111111-1111-1111-1111-111111111111"
BASE = "https://85.192.37.58.nip.io:8443"
BOT = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; Googlebot/2.1; "
        "+http://www.google.com/bot.html)"
    )
}
YANDEX_BOT = {
    "User-Agent": "Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)"
}
HUMAN = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0"}


def _manga(*, title: str = "Ванпанчмен", url_slug: str = "vanpanchmen") -> SimpleNamespace:
    return SimpleNamespace(
        id=MANGA_ID,
        source="mangapoisk",
        source_id="one-punch-man",
        title=title,
        title_en="One Punch Man",
        title_alt="One Punch-Man",
        url_slug=url_slug,
        description=(
            "Сайтама — герой по приколу. <script>alert('description')</script> "
            "Описание с амперсандом & кавычками \"quote\"."
        ),
        description_fallback=None,
        poster_url="https://cdn.example/cover.jpg",
        adult=False,
        genres=["Экшен", "Комедия"],
        year=2012,
        rating=9.1,
        rating_count=1200,
        url="https://source.example/manga/1",
        updated_at=datetime(2026, 11, 1, tzinfo=UTC),
        last_chapter_at=datetime(2026, 11, 1, tzinfo=UTC),
        chapters_count=2,
        chapters=[
            SimpleNamespace(
                id=CHAPTER_ID,
                volume=None,
                number="2",
                title="Глава 2",
                published_at=datetime(2026, 11, 1, tzinfo=UTC),
            ),
            SimpleNamespace(
                id="22222222-2222-2222-2222-222222222222",
                volume=None,
                number="1",
                title="",
                published_at=None,
            ),
        ],
        covers=[SimpleNamespace(url="https://cdn.example/cover.jpg", is_primary=True)],
    )


class FakeCatalog:
    def __init__(self, record: SimpleNamespace | None = None, *, fail: bool = False) -> None:
        self.record = record or _manga()
        self.fail = fail
        self.calls = 0

    async def manga(self, manga_id: str) -> SimpleNamespace:
        self.calls += 1
        if self.fail:
            raise RuntimeError("catalog is down")
        if manga_id != MANGA_ID:
            from manga_common.errors import NotFoundError

            raise NotFoundError("Manga not found")
        return self.record

    async def chapter_meta(self, chapter_id: str) -> SimpleNamespace:
        self.calls += 1
        if self.fail:
            raise RuntimeError("catalog is down")
        return SimpleNamespace(
            id=chapter_id,
            manga_id=MANGA_ID,
            volume=None,
            number="2",
            title="Глава 2",
            published_at=datetime(2026, 11, 1, tzinfo=UTC),
        )

    async def manga_list(self, params: dict[str, object]) -> SimpleNamespace:
        self.calls += 1
        if self.fail:
            raise RuntimeError("catalog is down")
        query = str(params.get("query") or "")
        items = [] if query == "ничего" else [self.record]
        return SimpleNamespace(items=items, total=len(items))


def _client(*, catalog: FakeCatalog | None = None) -> TestClient:
    prerender.reset_prerender_cache()
    app = FastAPI()
    app.state.settings = SimpleNamespace(
        public_web_url=BASE,
        google_site_verification="google-token",
        yandex_verification="yandex-token",
        web_internal_url="http://127.0.0.1:9",
        seo_prerender_cache_seconds=60.0,
        seo_prerender_timeout_seconds=2.0,
        seo_prerender_cache_max_items=32,
    )
    app.state.catalog = catalog or FakeCatalog()
    app.include_router(prerender.router)
    return TestClient(app)


def _json_ld(html_text: str) -> dict:
    match = re.search(
        r'<script type="application/ld\+json"[^>]*>(.*?)</script>',
        html_text,
        re.S,
    )
    assert match, "JSON-LD script missing"
    return json.loads(match.group(1))


def test_bot_detection_allowlist() -> None:
    for ua in (
        "Googlebot/2.1",
        "Mozilla/5.0 (compatible; YandexBot/3.0)",
        "Twitterbot/1.0",
        "TelegramBot (like TwitterBot)",
        "Mozilla/5.0 (compatible; bingbot/2.0)",
        "VKShare/1.0",
        "facebookexternalhit/1.1",
    ):
        assert prerender.is_bot(ua), ua
    for ua in (
        "Mozilla/5.0 (Windows NT 10.0) Chrome/120.0",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)",
        "",
        None,
    ):
        assert not prerender.is_bot(ua), ua


def test_old_manga_url_301s_to_slug_and_preserves_query() -> None:
    client = _client()
    response = client.get(
        f"/manga/{MANGA_ID}",
        headers=BOT,
        params={"page": "2"},
        follow_redirects=False,
    )
    assert response.status_code == 301
    assert response.headers["location"] == (
        f"{BASE}/manga/{MANGA_ID}-vanpanchmen?page=2"
    )


def test_mismatched_slug_301s_to_canonical_slug() -> None:
    client = _client()
    for stale_slug in ("old-slug", "ванпанчмен", ""):
        response = client.get(
            f"/manga/{MANGA_ID}-{stale_slug}",
            headers=BOT,
            follow_redirects=False,
        )
        assert response.status_code == 301
        assert response.headers["location"] == f"{BASE}/manga/{MANGA_ID}-vanpanchmen"


def test_bot_gets_full_html_and_valid_json_ld() -> None:
    client = _client()
    response = client.get(f"/manga/{MANGA_ID}-vanpanchmen", headers=BOT)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "User-Agent" in response.headers["vary"]
    assert "max-age=60" in response.headers["cache-control"]
    text = response.text

    assert "<title>Ванпанчмен — читать онлайн на русском | MangaPoisk Reborn</title>" in text
    assert '<link rel="canonical" href="' + f"{BASE}/manga/{MANGA_ID}-vanpanchmen" in text
    assert 'property="og:title"' in text
    assert 'property="og:description"' in text
    assert 'property="og:url"' in text
    assert 'property="og:image" content="https://cdn.example/cover.jpg"' in text
    assert 'name="twitter:card" content="summary_large_image"' in text
    assert 'name="twitter:image" content="https://cdn.example/cover.jpg"' in text
    assert 'name="google-site-verification" content="google-token"' in text
    assert 'name="yandex-verification" content="yandex-token"' in text
    assert "Экшен, Комедия" in text
    assert "Глав: 2" in text
    assert "Глава 2" in text
    assert f"/reader/{CHAPTER_ID}" in text

    # Description HTML is stripped, and user text cannot break out of the
    # JSON-LD script.
    assert "alert('description')" in text
    assert "<script>alert('description')</script>" not in text
    assert "</script><script>" not in text

    data = _json_ld(text)
    graph = data["@graph"]
    assert graph[0]["@type"] == ["ComicStory", "Book"]
    assert graph[0]["name"] == "Ванпанчмен"
    assert graph[0]["url"] == f"{BASE}/manga/{MANGA_ID}-vanpanchmen"
    assert graph[0]["inLanguage"] == "ru"
    assert graph[0]["isFamilyFriendly"] is True
    assert graph[0]["genre"] == ["Экшен", "Комедия"]
    assert graph[0]["aggregateRating"]["ratingValue"] == 9.1
    assert graph[1]["@type"] == "BreadcrumbList"
    assert [item["position"] for item in graph[1]["itemListElement"]] == [1, 2, 3]
    assert graph[1]["itemListElement"][2]["item"] == (
        f"{BASE}/manga/{MANGA_ID}-vanpanchmen"
    )


def test_xss_title_is_escaped_everywhere() -> None:
    title = 'Тайтл</title><script>alert("x")</script>'
    client = _client(catalog=FakeCatalog(_manga(title=title)))
    response = client.get(f"/manga/{MANGA_ID}-vanpanchmen", headers=BOT)
    assert response.status_code == 200
    text = response.text
    escaped_title = html.escape(title, quote=True)
    assert f"<title>{escaped_title} —" in text
    assert "<script>alert" not in text
    assert "&lt;script&gt;alert" in text
    data = _json_ld(text)
    assert data["@graph"][0]["name"] == title


def test_human_gets_spa_not_prerender(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_spa(request):  # type: ignore[no-untyped-def]
        return '<!doctype html><html><body><div id="root">SPA shell</div></body></html>'

    monkeypatch.setattr(prerender, "_fetch_spa_html", fake_spa)
    client = _client()
    response = client.get(f"/manga/{MANGA_ID}-vanpanchmen", headers=HUMAN)
    assert response.status_code == 200
    assert response.headers["x-prerender"] == "spa"
    assert response.headers["cache-control"] == "no-cache"
    assert 'id="root"' in response.text
    assert "application/ld+json" not in response.text


def test_reader_is_noindex_with_title_canonical() -> None:
    client = _client()
    response = client.get(f"/reader/{CHAPTER_ID}", headers=YANDEX_BOT)
    assert response.status_code == 200
    assert response.headers["x-robots-tag"] == "noindex, follow"
    text = response.text
    assert '<meta name="robots" content="noindex,follow" />' in text
    assert '<link rel="canonical" href="' + f"{BASE}/manga/{MANGA_ID}-vanpanchmen" in text
    assert "Страница чтения не индексируется" in text


def test_catalogue_empty_query_and_empty_results_are_noindex() -> None:
    client = _client()
    empty_q = client.get("/catalogue?q=", headers=BOT)
    assert empty_q.status_code == 200
    assert 'content="noindex,follow"' in empty_q.text
    assert empty_q.headers["x-robots-tag"] == "noindex, follow"

    empty_results = client.get("/catalogue?q=ничего", headers=BOT)
    assert 'content="noindex,follow"' in empty_results.text

    results = client.get("/catalogue?q=ван", headers=BOT)
    assert 'content="index,follow,max-image-preview:large"' in results.text
    assert "x-robots-tag" not in results.headers
    assert f"/manga/{MANGA_ID}-vanpanchmen" in results.text


def test_private_routes_are_noindex() -> None:
    client = _client()
    for path in ("/library", "/profile", "/admin", "/login", "/register"):
        response = client.get(path, headers=BOT)
        assert response.status_code == 200
        assert response.headers["x-robots-tag"] == "noindex, nofollow"
        assert 'content="noindex,nofollow"' in response.text


def test_catalog_down_never_returns_5xx_for_bots() -> None:
    client = _client(catalog=FakeCatalog(fail=True))
    response = client.get(f"/manga/{MANGA_ID}-vanpanchmen", headers=BOT)
    assert response.status_code == 200
    assert "noindex,follow" in response.text
    assert "Каталог временно недоступен" in response.text
    assert response.headers["x-prerender"] == "fallback"


def test_prerender_cache_headers_and_hit() -> None:
    client = _client()
    first = client.get(f"/manga/{MANGA_ID}-vanpanchmen", headers=BOT)
    second = client.get(f"/manga/{MANGA_ID}-vanpanchmen", headers=BOT)
    assert first.status_code == second.status_code == 200
    assert first.headers["x-prerender"] == "miss"
    assert second.headers["x-prerender"] == "hit"
    assert first.text == second.text
    # The route resolves the title on each request (to validate the slug and
    # redirect stale slugs); the expensive HTML render is cached.
    assert client.app.state.catalog.calls == 2


def test_unknown_manga_is_404_for_bots_and_spa_for_humans() -> None:
    client = _client()
    missing = "00000000-0000-0000-0000-000000000000"
    bot = client.get(f"/manga/{missing}-missing", headers=BOT)
    assert bot.status_code == 404
    assert "noindex,follow" in bot.text

    human = client.get(f"/manga/{missing}-missing", headers=HUMAN)
    assert human.status_code == 200
    assert human.headers["x-prerender"] == "spa"
