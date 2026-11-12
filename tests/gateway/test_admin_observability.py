from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from manga_common.alerts import AlertThresholds
from manga_common.errors import AppError, app_error_handler
from manga_common.security import require_admin
from services.gateway.app import api as gateway_api
from services.gateway.app.observability import (
    build_observability_snapshot,
    merge_db_snapshots,
    read_backup_status,
)


def _metrics_snapshot() -> dict:
    return {
        "http": {
            "total": 100,
            "errors_5xx": 3,
            "error_rate": 0.03,
            "windows": {
                "5m": {
                    "requests": 100,
                    "errors_5xx": 3,
                    "error_rate": 0.03,
                    "p95_ms": 2500.0,
                    "p50_ms": 100.0,
                    "p99_ms": 3000.0,
                }
            },
        },
        "db": {
            "errors_total": 10,
            "retries_total": 8,
            "exhausted_total": 1,
            "recovered_total": 7,
            "errors_1m": 2,
            "errors_5m": 6,
            "retries_5m": 5,
            "per_minute_5m": 6.0,
        },
    }


def test_build_observability_snapshot_merges_sources_and_alerts() -> None:
    now = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
    snapshot = build_observability_snapshot(
        metrics_snapshot=_metrics_snapshot(),
        services={"catalog": False, "media": True},
        catalog_stats={
            "pending_enrichment": 12_000,
            "sources": [{"source": "remanga", "pending": 9_000}],
        },
        crawl_states=[
            {
                "source": "remanga",
                "mode": "full",
                "status": "running",
                "page": 10,
                "total_pages": 100,
                "eta_seconds": 600,
                "last_run_at": (now - timedelta(minutes=45)).isoformat(),
                "next_run_at": (now + timedelta(minutes=5)).isoformat(),
                "last_error": None,
            },
            {
                "source": "mangalib",
                "mode": "full",
                "status": "failed",
                "page": 201,
                "total_pages": None,
                "eta_seconds": None,
                "last_run_at": now.isoformat(),
                "last_error": "HTTP 403",
            },
        ],
        media_stats={
            "archives": {"usage_percent": 85.0, "done_bytes": 100, "cap_bytes": 200},
            "image_cache": {"used_bytes": 300, "usage_percent": 3.0, "files": 2},
            "warnings": [],
        },
        backup={
            "configured": True,
            "status": "ok",
            "age_seconds": 27 * 3600,
            "last_success_at": (now - timedelta(hours=27)).isoformat(),
            "last_attempt_at": now.isoformat(),
            "last_error": None,
        },
        disk={"path": "/", "used_percent": 95.0, "free_bytes": 100},
        thresholds=AlertThresholds(),
        now=now,
    )

    assert snapshot["crawler"]["backlog"] == 12_000
    assert snapshot["crawler"]["backlog_by_source"]["remanga"] == 9_000
    assert snapshot["crawler"]["stalled"] == ["remanga"]
    assert snapshot["crawler"]["sources"][0]["progress_percent"] == 10.0
    assert snapshot["media"]["archive_usage_percent"] == 85.0
    keys = {alert["key"] for alert in snapshot["alerts"]}
    assert {
        "http_5xx_rate",
        "http_p95_latency",
        "service_down:catalog",
        "crawler_backlog",
        "crawler_stalled:remanga",
        "crawler_failed:mangalib:full",
        "archive_usage",
        "backup_stale",
        "disk_usage",
        "sqlite_lock_rate",
    }.issubset(keys)


def test_merge_db_snapshots_sums_services_and_keeps_breakdown() -> None:
    merged = merge_db_snapshots(
        {
            "gateway": {"errors_total": 0, "errors_5m": 0, "per_minute_5m": 0.0},
            "catalog": {
                "errors_total": 10,
                "retries_total": 8,
                "exhausted_total": 1,
                "recovered_total": 7,
                "errors_1m": 2,
                "errors_5m": 6,
                "retries_5m": 5,
                "per_minute_5m": 1.2,
            },
            "library": {
                "errors_total": 2,
                "retries_total": 1,
                "errors_1m": 0,
                "errors_5m": 1,
                "retries_5m": 1,
                "per_minute_5m": 0.2,
            },
        }
    )
    assert merged["errors_total"] == 12
    assert merged["retries_total"] == 9
    assert merged["errors_5m"] == 7
    assert merged["per_minute_5m"] == 1.4
    assert merged["by_service"]["catalog"]["errors_5m"] == 6
    assert merged["by_service"]["library"]["errors_5m"] == 1


def test_read_backup_status_handles_missing_and_present_files(tmp_path) -> None:
    missing = read_backup_status([tmp_path / "missing.json"])
    assert missing["configured"] is False
    assert missing["status"] == "missing"

    status_file = tmp_path / "status.json"
    status_file.write_text(
        '{"status":"ok","last_success_at":"2026-11-12T00:00:00Z",'
        '"last_attempt_at":"2026-11-12T00:00:00Z"}',
        encoding="utf-8",
    )
    present = read_backup_status(
        [status_file], now=datetime(2026, 11, 12, 6, 0, tzinfo=UTC)
    )
    assert present["configured"] is True
    assert present["status"] == "ok"
    assert present["age_seconds"] == 6 * 3600


def _client(snapshot: dict | None) -> TestClient:
    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.state.observability_snapshot = snapshot
    app.include_router(gateway_api.router)
    app.dependency_overrides[require_admin] = lambda: None
    return TestClient(app)


def test_admin_observability_endpoint_returns_snapshot() -> None:
    payload = {"generated_at": "2026-11-12T12:00:00Z", "alerts": [], "http": {}, "db": {}}
    with _client(payload) as client:
        response = client.get("/api/v1/admin/observability")
    assert response.status_code == 200
    assert response.json() == payload


def test_admin_observability_requires_admin() -> None:
    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.state.observability_snapshot = {}
    app.include_router(gateway_api.router)

    with TestClient(app) as client:
        response = client.get("/api/v1/admin/observability")
    assert response.status_code == 401
