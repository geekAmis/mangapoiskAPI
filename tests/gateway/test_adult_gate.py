from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from manga_common.auth import create_access_token
from manga_common.config import Settings, get_settings
from manga_common.errors import AppError, ForbiddenError, app_error_handler
from manga_common.schemas import (
    AgeStatusOut,
    ChapterDetailOut,
    ChapterOut,
    MangaDetailOut,
    MangaListResponse,
    SearchSuggestionOut,
    SourceOut,
    SuggestResponse,
)
from services.gateway.app.api import router

MANGA_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
CHAPTER_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


def _manga(adult: bool = True) -> MangaDetailOut:
    now = datetime.now(UTC)
    chapter = ChapterOut(
        id=CHAPTER_ID,
        manga_id=MANGA_ID,
        source="hentailib",
        source_id="1",
        number="1",
        title="Глава 1",
        page_count=0,
        adult_only=adult,
        requires_age_confirmation=adult,
        created_at=now,
        updated_at=now,
    )
    return MangaDetailOut(
        id=MANGA_ID,
        source="hentailib",
        source_id="adult-1",
        title="Взрослый тайтл",
        adult=True,
        adult_only=adult,
        requires_age_confirmation=adult,
        chapters=[chapter],
        created_at=now,
        updated_at=now,
    )


class FakeCatalog:
    def __init__(self, adult: bool = True) -> None:
        self.adult = adult
        self.adult_allowed_calls: list[bool] = []
        self.sources_allowed: list[bool] = []

    async def manga(self, manga_id: str, *, adult_allowed: bool = False):  # type: ignore[no-untyped-def]
        self.adult_allowed_calls.append(adult_allowed)
        if self.adult and not adult_allowed:
            raise ForbiddenError(
                "Для просмотра этого тайтла нужно подтвердить возраст 18+",
                code="age_confirmation_required",
                details={"manga_id": manga_id, "age_confirmation_required": True},
            )
        return _manga(self.adult)

    async def chapter(self, chapter_id: str, *, refresh: bool = True, adult_allowed: bool = False):  # type: ignore[no-untyped-def]
        self.adult_allowed_calls.append(adult_allowed)
        if self.adult and not adult_allowed:
            raise ForbiddenError(
                "Для просмотра этого тайтла нужно подтвердить возраст 18+",
                code="age_confirmation_required",
            )
        return ChapterDetailOut(
            id=CHAPTER_ID,
            manga_id=MANGA_ID,
            source="hentailib",
            source_id="1",
            number="1",
            title="Глава 1",
            adult_only=self.adult,
            requires_age_confirmation=self.adult,
            pages=[],
        )

    async def chapter_meta(self, chapter_id: str, *, adult_allowed: bool = False):  # type: ignore[no-untyped-def]
        self.adult_allowed_calls.append(adult_allowed)
        if self.adult and not adult_allowed:
            raise ForbiddenError(
                "Для просмотра этого тайтла нужно подтвердить возраст 18+",
                code="age_confirmation_required",
            )
        return ChapterOut(
            id=CHAPTER_ID,
            manga_id=MANGA_ID,
            source="hentailib",
            source_id="1",
            number="1",
            adult_only=self.adult,
            requires_age_confirmation=self.adult,
        )

    async def manga_list(self, params: dict[str, object]):  # type: ignore[no-untyped-def]
        self.adult_allowed_calls.append(bool(params.get("adult_allowed")))
        return MangaListResponse(
            items=[_manga(self.adult)] if params.get("adult_allowed") else [],
            total=0,
            page=1,
            limit=24,
            has_next=False,
        )

    async def search(self, q: str, *, source=None, page=1, limit=24, adult_allowed=False):  # type: ignore[no-untyped-def]
        self.adult_allowed_calls.append(adult_allowed)
        return MangaListResponse(items=[], total=0, page=page, limit=limit, has_next=False)

    async def suggest(self, q: str, *, limit=6, adult_allowed=False):  # type: ignore[no-untyped-def]
        self.adult_allowed_calls.append(adult_allowed)
        return SuggestResponse(
            query=q,
            items=[
                SearchSuggestionOut(
                    id=str(MANGA_ID),
                    title="Безопасный тайтл",
                    source="mangapoisk",
                )
            ],
            total=1,
        )

    async def sources(self, *, adult_allowed: bool = False):  # type: ignore[no-untyped-def]
        self.sources_allowed.append(adult_allowed)
        return [
            SourceOut(
                code="hentailib" if adult_allowed else "mangapoisk",
                name="HentaiLib" if adult_allowed else "MangaPoisk",
                base_url="https://hentailib.me" if adult_allowed else "https://mangapoisk.me",
                adult_only=adult_allowed,
            )
        ]

    async def chapters(self, manga_id: str, *, page=1, limit=200, query=None, adult_allowed=False):  # type: ignore[no-untyped-def]
        self.adult_allowed_calls.append(adult_allowed)
        if self.adult and not adult_allowed:
            raise ForbiddenError("age", code="age_confirmation_required")
        return []

    async def variants(self, manga_id: str, *, adult_allowed: bool = False):  # type: ignore[no-untyped-def]
        self.adult_allowed_calls.append(adult_allowed)
        if self.adult and not adult_allowed:
            raise ForbiddenError("age", code="age_confirmation_required")
        return SimpleNamespace(primary_id=MANGA_ID, items=[])

    async def home_updates(self, limit: int = 25):  # type: ignore[no-untyped-def]
        return SimpleNamespace(items=[], total=0)


class FakeLibrary:
    def __init__(self, confirmed: bool = False) -> None:
        self.confirmed = confirmed
        self.status_calls = 0

    async def age_status(self, authorization: str) -> AgeStatusOut:
        self.status_calls += 1
        return AgeStatusOut(
            age_confirmed=self.confirmed,
            age_confirmed_at=datetime.now(UTC) if self.confirmed else None,
        )

    async def confirm_age(self, authorization: str) -> AgeStatusOut:
        self.confirmed = True
        return AgeStatusOut(age_confirmed=True, age_confirmed_at=datetime.now(UTC))

    async def revoke_age(self, authorization: str) -> AgeStatusOut:
        self.confirmed = False
        return AgeStatusOut(age_confirmed=False, age_confirmed_at=None)


class FakeMedia:
    def __init__(self) -> None:
        self.calls = 0

    async def stream(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.calls += 1
        return httpx.Response(200, content=b"image")


def _app(confirmed: bool = False) -> tuple[FastAPI, FakeCatalog, FakeLibrary, FakeMedia]:
    settings = Settings(
        _env_file=None,
        environment="test",
        jwt_secret="gateway-age-test-secret-which-is-long-enough",
        internal_token="test-internal-token",
        public_web_url="https://example.test",
        public_api_url="https://example.test",
    )
    catalog = FakeCatalog()
    library = FakeLibrary(confirmed)
    media = FakeMedia()
    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)
    app.include_router(router)
    app.state.settings = settings
    app.state.catalog = catalog
    app.state.parser = SimpleNamespace(sources=lambda: [])
    app.state.library = library
    app.state.media = media
    app.dependency_overrides[get_settings] = lambda: settings
    return app, catalog, library, media


def _token(app: FastAPI, *, confirmed: bool) -> dict[str, str]:
    settings = app.dependency_overrides[get_settings]()
    token, _ = create_access_token(
        settings,
        subject=str(uuid.uuid4()),
        role="user",
        extra={
            "age_confirmed": confirmed,
            "age_confirmed_at": datetime.now(UTC).isoformat() if confirmed else None,
        },
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_guest_direct_adult_manga_is_403_without_content() -> None:
    app, catalog, _, _ = _app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/manga/{MANGA_ID}")

    assert response.status_code == 403
    payload = response.json()
    assert payload["error"]["code"] == "age_confirmation_required"
    assert "Взрослый тайтл" not in response.text
    assert catalog.adult_allowed_calls == [False]


@pytest.mark.asyncio
async def test_authenticated_unconfirmed_user_gets_403() -> None:
    app, catalog, _, _ = _app(confirmed=False)
    transport = httpx.ASGITransport(app=app)
    headers = _token(app, confirmed=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/manga/{MANGA_ID}", headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "age_confirmation_required"
    assert "Взрослый тайтл" not in response.text
    assert catalog.adult_allowed_calls == [False]


@pytest.mark.asyncio
async def test_confirmed_user_reads_adult_and_revoke_hides_again() -> None:
    app, _, library, _ = _app(confirmed=True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = _token(app, confirmed=True)
        first = await client.get(f"/api/v1/manga/{MANGA_ID}", headers=headers)
        assert first.status_code == 200
        assert first.json()["title"] == "Взрослый тайтл"
        assert first.headers.get("x-robots-tag") == "noindex, nofollow"

        library.confirmed = False
        second = await client.get(f"/api/v1/manga/{MANGA_ID}", headers=headers)
        assert second.status_code == 403
        assert "Взрослый тайтл" not in second.text


@pytest.mark.asyncio
async def test_search_and_suggest_pass_confirmation_state() -> None:
    app, catalog, library, _ = _app(confirmed=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/api/v1/manga", params={"query": "тест"})
        await client.get("/api/v1/manga/suggest", params={"q": "тест"})
        assert catalog.adult_allowed_calls[-2:] == [False, False]

        library.confirmed = True
        headers = _token(app, confirmed=True)
        await client.get("/api/v1/manga", params={"query": "тест"}, headers=headers)
        await client.get("/api/v1/manga/suggest", params={"q": "тест"}, headers=headers)
        assert catalog.adult_allowed_calls[-2:] == [True, True]


@pytest.mark.asyncio
async def test_ads_are_empty_for_adult_surfaces() -> None:
    app, _, _, _ = _app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/ads/config", params={"adult": "true"})
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_age_status_confirm_and_revoke_endpoints() -> None:
    app, _, library, _ = _app()
    transport = httpx.ASGITransport(app=app)
    headers = _token(app, confirmed=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        status = await client.get("/api/v1/profile/age-status", headers=headers)
        assert status.json()["age_confirmed"] is False

        confirmed = await client.post("/api/v1/profile/age-confirm", headers=headers)
        assert confirmed.status_code == 200
        assert confirmed.json()["age_confirmed"] is True

        revoked = await client.delete("/api/v1/profile/age-confirm", headers=headers)
        assert revoked.status_code == 200
        assert revoked.json()["age_confirmed"] is False
    assert library.status_calls == 1


@pytest.mark.asyncio
async def test_direct_chapter_route_is_blocked_without_content() -> None:
    app, _, _, _ = _app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/chapters/{CHAPTER_ID}")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "age_confirmation_required"
    assert "Глава 1" not in response.text


@pytest.mark.asyncio
async def test_direct_reader_image_is_blocked_before_media() -> None:
    app, _, _, media = _app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/v1/chapters/{CHAPTER_ID}/images/1")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "age_confirmation_required"
    assert media.calls == 0


@pytest.mark.asyncio
async def test_guest_sources_do_not_include_adult_source() -> None:
    app, catalog, _, _ = _app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/sources")
    assert response.status_code == 200
    assert [item["code"] for item in response.json()] == ["mangapoisk"]
    assert catalog.sources_allowed == [False]
