from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace

from fastapi import FastAPI, Response
from fastapi.testclient import TestClient
from manga_common.config import get_settings
from manga_common.errors import AppError, app_error_handler
from manga_common.profile_schemas import PublicProfileOut, RankOut
from services.gateway.app.api import _progress_activity
from services.gateway.app.config import GatewaySettings
from services.gateway.app.profile_api import _apply_profile_headers, router

MANGA = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
OTHER = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


class FakeLibrary:
    def __init__(self) -> None:
        self.profile_data = make_profile()

    async def profile(
        self, handle: str, *, viewer_id: str | None = None, timezone: str | None = None
    ) -> PublicProfileOut:
        return self.profile_data


def make_profile(*, indexable: bool = True, owner: bool = False) -> PublicProfileOut:
    return PublicProfileOut(
        username="reader",
        display_name="Reader",
        joined_at=date(2026, 1, 1),
        rank=RankOut(code="reader", label="Читатель", min_level=1),
        indexable=indexable,
        is_owner=owner,
    )


def make_client() -> tuple[TestClient, FakeLibrary]:
    settings = GatewaySettings(
        _env_file=None,
        service_name="gateway-profile-test",
        environment="test",
        jwt_secret="gateway-profile-test-secret",
        internal_token="gateway-profile-internal",
        log_level="WARNING",
        log_json=False,
    )
    library = FakeLibrary()
    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.include_router(router)
    app.state.library = library
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app), library


def test_public_profile_headers_are_indexable_by_default() -> None:
    client, library = make_client()
    response = client.get("/api/v1/users/reader")
    assert response.status_code == 200, response.text
    assert response.headers["X-Robots-Tag"] == "index, follow"
    assert response.headers["Cache-Control"] == "public, max-age=60"

    library.profile_data = make_profile(indexable=False)
    hidden = client.get("/api/v1/users/reader")
    assert hidden.status_code == 200
    assert hidden.headers["X-Robots-Tag"] == "noindex, nofollow"


def test_owner_profile_is_never_shared_cached() -> None:
    response = Response()
    _apply_profile_headers(response, make_profile(owner=True))
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["X-Robots-Tag"] == "noindex, nofollow"


def test_finish_detection_requires_trusted_catalogue_pages() -> None:
    manga = SimpleNamespace(
        id=MANGA,
        title="Тайтл",
        poster_url="https://example.test/p.jpg",
        genres=["Экшен"],
        chapters=[
            SimpleNamespace(number="1"),
            SimpleNamespace(number="2"),
        ],
    )
    chapter = SimpleNamespace(
        manga_id=MANGA,
        number="2",
        volume=None,
        title="Финал",
        page_count=20,
    )

    finished = _progress_activity(manga, chapter, page=20, total_pages=1)
    assert finished["title_completed"] is True
    assert finished["manga_title"] == "Тайтл"

    not_last_page = _progress_activity(manga, chapter, page=19, total_pages=20)
    assert not_last_page["title_completed"] is False

    forged_total = _progress_activity(
        manga,
        SimpleNamespace(
            manga_id=MANGA,
            number="2",
            volume=None,
            title="Финал",
            page_count=0,
        ),
        page=1,
        total_pages=1,
    )
    assert forged_total["title_completed"] is False

    wrong_title = _progress_activity(
        manga,
        SimpleNamespace(
            manga_id=OTHER,
            number="2",
            volume=None,
            title="Финал",
            page_count=20,
        ),
        page=20,
        total_pages=20,
    )
    assert wrong_title["title_completed"] is False
