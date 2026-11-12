from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from xml.etree import ElementTree

from fastapi import FastAPI
from fastapi.testclient import TestClient
from services.gateway.app import seo


def _manga(manga_id: str, *, chapters: int, updated: datetime | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=manga_id,
        chapters_count=chapters,
        last_chapter_at=updated,
        updated_at=updated,
    )


class FakeCatalog:
    def __init__(self, pages: dict[int, SimpleNamespace]) -> None:
        self.pages = pages
        self.calls = 0

    async def manga_list(self, params: dict[str, object]) -> SimpleNamespace:
        self.calls += 1
        return self.pages[int(params["page"])]


def _client(pages: dict[int, SimpleNamespace]) -> TestClient:
    app = FastAPI()
    app.state.settings = SimpleNamespace(public_web_url="https://example.test")
    app.state.catalog = FakeCatalog(pages)
    app.include_router(seo.router)
    return TestClient(app)


def test_build_sitemap_xml_escapes_and_limits(monkeypatch) -> None:
    monkeypatch.setattr(seo, "SITEMAP_MAX_URLS", 2)
    xml = seo.build_sitemap_xml(
        [
            ("https://example.test/?a=1&b=2", None),
            ("https://example.test/?a=1&b=2", None),
            ("https://example.test/manga/1", "2026-01-02"),
            ("https://example.test/manga/2", None),
        ]
    )
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert "&amp;" in xml
    assert xml.count("<url>") == 2
    assert "<lastmod>2026-01-02</lastmod>" in xml
    assert xml.rstrip().endswith("</urlset>")

    root = ElementTree.fromstring(xml)
    assert root.tag.endswith("urlset")
    assert len(root.findall("{http://www.sitemaps.org/schemas/sitemap/0.9}url")) == 2


def test_lastmod_accepts_iso_strings_and_clamps_future_dates() -> None:
    past = (date.today() - timedelta(days=10)).isoformat()
    future = (date.today() + timedelta(days=30)).isoformat()
    assert seo._lastmod(f"{past}T12:00:00Z") == past
    assert seo._lastmod(f"{future}T12:00:00") is None
    assert seo._lastmod("not-a-date") is None
    assert seo._lastmod(None) is None


def test_sitemap_lists_only_titles_with_chapters_and_caches() -> None:
    seo.reset_sitemap_cache()
    client = _client(
        {
            1: SimpleNamespace(
                items=[
                    _manga("with-chapters", chapters=3, updated=datetime(2026, 1, 2)),
                    _manga("empty-title", chapters=0),
                ],
                has_next=True,
            ),
            2: SimpleNamespace(
                items=[_manga("second-page", chapters=1)],
                has_next=False,
            ),
        }
    )

    response = client.get("/sitemap.xml")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert "<loc>https://example.test/</loc>" in response.text
    assert "<loc>https://example.test/manga/with-chapters</loc>" in response.text
    assert "<loc>https://example.test/manga/second-page</loc>" in response.text
    assert "empty-title" not in response.text
    assert "<lastmod>2026-01-02</lastmod>" in response.text

    catalog = client.app.state.catalog
    calls_after_first_request = catalog.calls
    assert calls_after_first_request == 2

    second = client.get("/api/v1/sitemap.xml")
    assert second.status_code == 200
    assert second.text == response.text
    assert catalog.calls == calls_after_first_request
    seo.reset_sitemap_cache()


def test_sitemap_serves_stale_copy_when_catalog_fails() -> None:
    seo.reset_sitemap_cache()
    client = _client(
        {
            1: SimpleNamespace(
                items=[_manga("cached-title", chapters=1)],
                has_next=False,
            )
        }
    )
    first = client.get("/sitemap.xml")
    assert first.status_code == 200

    class BrokenCatalog:
        async def manga_list(self, params: dict[str, object]) -> SimpleNamespace:
            raise RuntimeError("catalog is down")

    client.app.state.catalog = BrokenCatalog()
    # Force expiry without waiting for the real TTL.
    seo._cache = (0.0, first.text)  # type: ignore[attr-defined]
    stale = client.get("/sitemap.xml")
    assert stale.status_code == 200
    assert stale.text == first.text
    seo.reset_sitemap_cache()
