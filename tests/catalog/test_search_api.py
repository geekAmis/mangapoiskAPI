from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from manga_common.db import create_all, create_engine, create_session_factory
from manga_common.security import require_internal_token
from services.catalog.app.api import get_service, router
from services.catalog.app.config import CatalogSettings
from services.catalog.app.migrations import ensure_runtime_schema
from services.catalog.app.search_backfill import bootstrap_search_index
from services.catalog.app.service import CatalogService

from tests.fixtures.search_titles import TITLES, detail_from_spec


class ExplodingParser:
    async def manga(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("parser must not be called")

    async def chapter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("parser must not be called")

    async def sources(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("parser must not be called")


@pytest.fixture()
async def api(tmp_path: Path):
    db_path = tmp_path / "search-api.db"
    settings = CatalogSettings(
        service_name="catalog-search-api-test",
        catalog_database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
    )
    engine = create_engine(settings.catalog_dsn)
    await create_all(engine)
    await ensure_runtime_schema(engine)
    service = CatalogService(settings, create_session_factory(engine), ExplodingParser())  # type: ignore[arg-type]
    for spec in TITLES:
        await service.import_detail(detail_from_spec(spec))
    await bootstrap_search_index(service.session_factory)

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_internal_token] = lambda: None
    app.dependency_overrides[get_service] = lambda: service
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_suggest_endpoint_is_local_and_ranked(api) -> None:
    response = await api.get("/internal/manga/suggest", params={"q": "чензо мен", "limit": 5})
    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "чензо мен"
    assert payload["items"]
    assert payload["items"][0]["title"] == "Человек-бензопила"
    assert payload["items"][0]["reason"] in {"title", "alternative", "genre", "description"}
    assert len(payload["items"]) <= 5

    punctuation = await api.get("/internal/manga/suggest", params={"q": "!!!", "limit": 5})
    assert punctuation.status_code == 200
    assert punctuation.json()["items"] == []


@pytest.mark.asyncio
async def test_search_endpoint_exposes_relevance_and_pagination(api) -> None:
    response = await api.get("/internal/manga/search", params={"q": "solo leveling", "limit": 3})
    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["source_id"] == "solo-leveling"
    assert payload["total"] >= 1

    page = await api.get(
        "/internal/manga/search", params={"q": "манхва", "limit": 3, "page": 2}
    )
    assert page.status_code == 200
    assert page.json()["page"] == 2
    assert page.json()["items"]


@pytest.mark.asyncio
async def test_backfill_progress_is_exposed(api) -> None:
    state = await api.get("/internal/search/backfill")
    assert state.status_code == 200
    payload = state.json()
    assert payload["status"] == "completed"
    assert payload["total"] == len(TITLES)
    assert payload["remaining"] == 0
    assert payload["progress_percent"] == 100.0

    stats = await api.get("/internal/stats")
    assert stats.status_code == 200
    assert stats.json()["search_backfill"]["status"] == "completed"


@pytest.mark.asyncio
async def test_search_query_validation(api) -> None:
    empty = await api.get("/internal/manga/search", params={"q": ""})
    assert empty.status_code == 422
    long = await api.get("/internal/manga/suggest", params={"q": "x" * 201})
    assert long.status_code == 422
