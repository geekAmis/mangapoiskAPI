from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from manga_common.source_models import (
    ChapterDetail,
    MangaDetail,
    SourceCapabilities,
    SourceHome,
    SourceInfo,
    SourceSearchResult,
)
from services.parser.app.main import create_app

TOKEN_HEADERS = {"X-Internal-Token": "test-internal-token"}


class FakeAdapter:
    info = SourceInfo(
        code="fake",
        name="Fake source",
        base_url="https://example.test",
        enabled=True,
        capabilities=SourceCapabilities(search=True),
    )

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    async def search(self, query: str, page: int = 1) -> SourceSearchResult:
        self.calls.append((query, page))
        return SourceSearchResult(source="fake", items=[], page=page, total=0)

    async def get_manga(self, source_id: str, *, url: str | None = None, **_: Any) -> MangaDetail:
        raise NotImplementedError

    async def get_chapter(self, source_id: str, *, url: str | None = None) -> ChapterDetail:
        raise NotImplementedError

    async def latest(self) -> SourceHome:
        return SourceHome(source="fake")


def test_sources_requires_internal_token(settings) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        unauthorised = client.get("/internal/sources")
        assert unauthorised.status_code == 401
        assert unauthorised.json()["error"]["code"] == "invalid_internal_token"

        response = client.get("/internal/sources", headers=TOKEN_HEADERS)
        assert response.status_code == 200
        sources = {item["code"]: item for item in response.json()}
        assert set(sources) == {
            "mangapoisk",
            "mangalib",
            "remanga",
            "readmanga",
            "mangadex",
            "hentailib",
        }
        assert sources["mangapoisk"]["enabled"] is True
        assert sources["remanga"]["enabled"] is True
        assert sources["remanga"]["capabilities"]["search"] is True
        assert sources["remanga"]["capabilities"]["catalog"] is True


def test_health_and_ready(settings) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["service"] == "parser-test"

        ready = client.get("/ready")
        assert ready.status_code == 200
        payload = ready.json()
        assert payload["status"] == "ready"
        assert payload["checks"] == {"cache": True}


def test_unknown_and_disabled_source_are_404(settings) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        unknown = client.get(
            "/internal/search",
            params={"source": "nope", "q": "x"},
            headers=TOKEN_HEADERS,
        )
        assert unknown.status_code == 404
        assert unknown.json()["error"]["code"] == "source_not_found"

        disabled = client.get(
            "/internal/search",
            params={"source": "readmanga", "q": "x"},
            headers=TOKEN_HEADERS,
        )
        assert disabled.status_code == 404
        assert disabled.json()["error"]["code"] == "source_disabled"


def test_validation_errors_use_typed_shape(settings) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        missing_query = client.get(
            "/internal/search",
            params={"source": "mangapoisk"},
            headers=TOKEN_HEADERS,
        )
        assert missing_query.status_code == 422
        body = missing_query.json()
        assert body["error"]["code"] == "validation_error"
        assert isinstance(body["error"]["details"], list)

        missing_identifier = client.get(
            "/internal/manga",
            params={"source": "mangapoisk"},
            headers=TOKEN_HEADERS,
        )
        assert missing_identifier.status_code == 422
        assert missing_identifier.json()["error"]["code"] == "missing_source_id"


def test_fake_adapter_is_dispatched(settings) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        fake = FakeAdapter()
        app.state.registry.register(fake)

        response = client.get(
            "/internal/search",
            params={"source": "fake", "q": "hello", "page": 2},
            headers=TOKEN_HEADERS,
        )
        assert response.status_code == 200
        assert response.json()["source"] == "fake"
        assert response.json()["page"] == 2
        assert fake.calls == [("hello", 2)]

        home = client.get(
            "/internal/home",
            params={"source": "fake"},
            headers=TOKEN_HEADERS,
        )
        assert home.status_code == 200
        assert home.json() == {"source": "fake", "popular": [], "latest": []}
