from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from manga_common.db import create_all, create_engine, create_session_factory
from manga_common.security import require_internal_token
from manga_common.source_models import ChapterSummary, MangaDetail, MangaSummary
from services.catalog.app.api import get_service, router
from services.catalog.app.config import CatalogSettings
from services.catalog.app.service import CatalogService


def manga_detail(source_id: str, *, title: str, genres: list[str]) -> MangaDetail:
    return MangaDetail(
        source="mangapoisk",
        source_id=source_id,
        slug=source_id,
        title=title,
        description=f"Описание {title}",
        poster_url=f"https://cdn.example/{source_id}.jpg",
        genres=genres,
        chapters=[
            ChapterSummary(
                source="mangapoisk",
                source_id=f"{source_id}-1",
                manga_source_id=source_id,
                number="1",
                title="Глава 1",
                published_at=datetime(2026, 5, 1, tzinfo=UTC),
            )
        ],
    )


@pytest.fixture
async def api(tmp_path: Path):
    db_path = tmp_path / "api.db"
    settings = CatalogSettings(
        service_name="catalog-test",
        catalog_database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
    )
    engine = create_engine(settings.catalog_dsn)
    await create_all(engine)
    service = CatalogService(settings, create_session_factory(engine), None)  # type: ignore[arg-type]
    await service.import_detail(
        manga_detail("and-title", title="Ужас и фэнтези", genres=["Ужасы", "Фэнтези"])
    )
    await service.import_detail(
        manga_detail("fantasy-title", title="Только фэнтези", genres=["Фэнтези"])
    )
    await service.import_summary(
        MangaSummary(
            source="mangapoisk",
            source_id="stub-title",
            title="Пустышка",
            chapters_count=0,
        )
    )

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
async def test_stats_reports_enrichment_backlog(api) -> None:
    response = await api.get("/internal/stats")
    assert response.status_code == 200
    payload = response.json()
    assert payload["manga"] == 3
    assert payload["pending"] == 1
    assert payload["pending_enrichment"] >= 1
    source = next(item for item in payload["sources"] if item["source"] == "mangapoisk")
    assert source["pending"] == 1


@pytest.mark.asyncio
async def test_crawl_state_round_trips_eta(api) -> None:
    payload = {
        "source": "mangapoisk",
        "mode": "full",
        "page": 42,
        "status": "running",
        "total_pages": 100,
        "items_seen": 420,
        "items_imported": 400,
        "eta_seconds": 360,
    }
    saved = await api.put("/internal/crawl-state/mangapoisk", json=payload)
    assert saved.status_code == 200
    assert saved.json()["eta_seconds"] == 360

    loaded = await api.get("/internal/crawl-state/mangapoisk")
    assert loaded.status_code == 200
    assert loaded.json()["page"] == 42
    assert loaded.json()["eta_seconds"] == 360


@pytest.mark.asyncio
async def test_public_list_hides_empty_and_supports_include_empty(api) -> None:
    default = await api.get("/internal/manga")
    assert default.status_code == 200
    assert default.json()["total"] == 2
    assert all(item["source_id"] != "stub-title" for item in default.json()["items"])

    with_empty = await api.get("/internal/manga", params={"include_empty": "true"})
    assert with_empty.status_code == 200
    assert with_empty.json()["total"] == 3

    search = await api.get("/internal/manga/search", params={"q": "Пустышка"})
    assert search.json()["total"] == 0
    search_empty = await api.get(
        "/internal/manga/search", params={"q": "Пустышка", "include_empty": "true"}
    )
    assert search_empty.json()["total"] == 1


@pytest.mark.asyncio
async def test_genre_and_filter_and_genre_endpoint(api) -> None:
    both = await api.get("/internal/manga", params={"genres": "horror+fantasy"})
    assert both.status_code == 200
    assert both.json()["total"] == 1
    assert both.json()["items"][0]["source_id"] == "and-title"
    assert both.json()["items"][0]["genre_slugs"] == ["fantasy", "horror"]
    assert both.json()["items"][0]["genre_details"] == [
        {"slug": "fantasy", "label": "Фэнтези"},
        {"slug": "horror", "label": "Ужасы"},
    ]

    encoded = await api.get("/internal/manga?genres=horror%2Bfantasy")
    assert encoded.json()["total"] == 1

    genres = await api.get("/internal/genres")
    assert genres.status_code == 200
    payload = genres.json()
    by_slug = {item["slug"]: item for item in payload["items"]}
    assert by_slug["horror"]["label"] == "Ужасы"
    assert by_slug["horror"]["count"] == 1
    assert by_slug["fantasy"]["count"] == 2


@pytest.mark.asyncio
async def test_home_updates_contract(api) -> None:
    response = await api.get("/internal/home/updates", params={"limit": 25})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    first = payload["items"][0]
    for field in (
        "manga_id",
        "manga_title",
        "poster_url",
        "source",
        "chapter_id",
        "chapter_number",
        "chapter_title",
        "published_at",
        "added_at",
    ):
        assert field in first


@pytest.mark.asyncio
async def test_reset_enrichment_requeues_titles(api) -> None:
    response = await api.post("/internal/maintenance/reset-enrichment")
    assert response.status_code == 200
    assert response.json()["queued"] >= 2
    pending = await api.get("/internal/manga/pending", params={"source": "mangapoisk"})
    assert pending.status_code == 200
    assert {item["source_id"] for item in pending.json()["items"]} >= {
        "and-title",
        "fantasy-title",
        "stub-title",
    }


@pytest.mark.asyncio
async def test_enrichment_stats_and_failure_endpoint(api) -> None:
    stats = await api.get("/internal/enrichment/stats", params={"rate_per_minute": 36})
    assert stats.status_code == 200
    payload = stats.json()
    assert payload["pending"] >= 1
    assert payload["estimated_seconds"] > 0
    assert {item["source"] for item in payload["sources"]} == {"mangapoisk"}

    listing = await api.get("/internal/manga", params={"include_empty": "true"})
    stub_id = next(
        item["id"] for item in listing.json()["items"] if item["source_id"] == "stub-title"
    )
    failed = await api.post(
        f"/internal/manga/{stub_id}/enrichment-failure",
        json={"error": "403 Forbidden", "kind": "forbidden"},
    )
    assert failed.status_code == 200
    assert failed.json()["attempts"] == 1
    assert failed.json()["retry_at"]

    stats = await api.get("/internal/enrichment/stats", params={"rate_per_minute": 36})
    assert stats.json()["retrying"] >= 1

    rotated = await api.post(
        "/internal/maintenance/rotate-enrichment",
        params={"source": "mangapoisk", "limit": 1},
    )
    assert rotated.status_code == 200
    assert rotated.json()["queued"] == 1


@pytest.mark.asyncio
async def test_crawl_state_endpoints(api) -> None:
    payload = {
        "source": "mangapoisk",
        "mode": "full",
        "page": 7,
        "status": "running",
        "last_error": "timeout",
        "total_pages": 163,
        "items_seen": 280,
        "items_imported": 250,
    }
    saved = await api.put("/internal/crawl-state/mangapoisk", json=payload)
    assert saved.status_code == 200
    assert saved.json()["page"] == 7

    loaded = await api.get("/internal/crawl-state/mangapoisk", params={"mode": "full"})
    assert loaded.status_code == 200
    assert loaded.json()["status"] == "running"
    assert loaded.json()["last_error"] == "timeout"

    listing = await api.get("/internal/crawl-state", params={"source": "mangapoisk"})
    assert listing.status_code == 200
    assert len(listing.json()) == 1
