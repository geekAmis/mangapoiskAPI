from __future__ import annotations

from datetime import UTC, datetime, timedelta

from services.gateway.app.api import _build_crawler_status


def _catalog_stats() -> dict:
    return {
        "manga": 28_929,
        "chapters": 137_823,
        "pending": 27_597,
        "sources": [
            {
                "source": "mangapoisk",
                "manga": 6_122,
                "chapters": 646_945,
                "pending": 6_122,
            },
            {
                "source": "mangalib",
                "manga": 11_552,
                "chapters": 108_708,
                "pending": 11_552,
            },
        ],
    }


def _media_stats(*, usage: float = 2.2) -> dict:
    return {
        "archives": {
            "total": 440,
            "done": 109,
            "failed": 331,
            "pending": 0,
            "done_bytes": 733 * 1024 * 1024,
            "db_bytes": 1_700_000,
            "cap_bytes": 25 * 1024 * 1024 * 1024,
            "usage_percent": usage,
        },
        "image_cache_bytes": 1_800_000_000,
        "image_cache_files": 42_000,
    }


def test_build_crawler_status_merges_sources_and_states() -> None:
    now = datetime(2026, 11, 12, 6, 0, tzinfo=UTC)
    states = [
        {
            "source": "mangapoisk",
            "mode": "full",
            "status": "running",
            "page": 50,
            "total_pages": 100,
            "items_seen": 500,
            "items_imported": 480,
            "eta_seconds": 600,
            "last_run_at": (now - timedelta(seconds=20)).isoformat(),
        },
        {
            "source": "mangalib",
            "mode": "full",
            "status": "failed",
            "page": 201,
            "total_pages": None,
            "items_seen": 12_000,
            "items_imported": 12_000,
            "last_error": "NotFoundError: MangaLib: resource not found",
            "last_run_at": (now - timedelta(minutes=2)).isoformat(),
        },
        {
            "source": "mangalib",
            "mode": "incremental",
            "status": "failed",
            "last_error": "UpstreamError: Upstream returned HTTP 403",
            "last_run_at": (now - timedelta(minutes=2)).isoformat(),
        },
    ]

    result = _build_crawler_status(
        _catalog_stats(), states, _media_stats(), generated_at=now
    )

    assert result.catalog_manga == 28_929
    assert result.enrichment_pending == 27_597
    assert [item.source for item in result.sources] == ["mangalib", "mangapoisk"]
    mangapoisk = next(item for item in result.sources if item.source == "mangapoisk")
    assert mangapoisk.progress_percent == 50.0
    assert mangapoisk.eta_seconds == 600
    assert mangapoisk.full is not None and mangapoisk.full.status == "running"
    mangalib = next(item for item in result.sources if item.source == "mangalib")
    assert mangalib.progress_percent is None
    assert mangalib.incremental is not None
    assert any("mangalib: full-обход завершился ошибкой" in item for item in result.warnings)
    assert any("mangalib: incremental-обход завершился ошибкой" in item for item in result.warnings)
    assert any("Очередь обогащения" in item for item in result.warnings)


def test_build_crawler_status_flags_stalled_crawl_and_archive_pressure() -> None:
    now = datetime(2026, 11, 12, 6, 0, tzinfo=UTC)
    states = [
        {
            "source": "remanga",
            "mode": "full",
            "status": "running",
            "page": 340,
            "items_seen": 10_168,
            "items_imported": 10_167,
            "last_run_at": (now - timedelta(minutes=45)).isoformat(),
        }
    ]

    result = _build_crawler_status(
        {"manga": 10, "chapters": 100, "pending": 0, "sources": []},
        states,
        _media_stats(usage=85.0),
        generated_at=now,
    )

    assert any("не обновлял прогресс более 15 минут" in item for item in result.warnings)
    assert any("LRU" in item for item in result.warnings)
    assert result.sources[0].eta_seconds is None


def test_build_crawler_status_survives_empty_upstreams() -> None:
    result = _build_crawler_status({}, [], {})

    assert result.sources == []
    assert result.archive.total == 0
    assert result.catalog_manga == 0
    assert result.enrichment_pending == 0


def test_build_crawler_status_accepts_media_lru_payload_shape() -> None:
    media = {
        "archives": {
            "total": 1,
            "done": 1,
            "failed": 0,
            "pending": 0,
            "done_bytes": 1024,
            "db_bytes": 2048,
            "cap_bytes": 4096,
            "evictions": 0,
            "last_pruned_at": None,
            "usage_percent": 25.0,
            "level": "ok",
        },
        "image_cache": {
            "used_bytes": 1234,
            "cap_bytes": 10_000,
            "files": 7,
            "evictions": 2,
            "last_pruned_at": None,
            "usage_percent": 12.3,
            "level": "ok",
        },
        "warnings": [],
    }

    result = _build_crawler_status({}, [], media)

    assert result.image_cache_bytes == 1234
    assert result.image_cache_files == 7
    assert result.archive.cap_bytes == 4096
    assert result.archive.usage_percent == 25.0


def test_build_crawler_status_uses_pending_enrichment_fallback() -> None:
    result = _build_crawler_status({"pending_enrichment": 6000}, [], {})

    assert result.enrichment_pending == 6000
    assert any("Очередь обогащения" in item for item in result.warnings)
