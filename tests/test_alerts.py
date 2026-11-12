from __future__ import annotations

from manga_common.alerts import (
    Alert,
    AlertDeduplicator,
    AlertThresholds,
    evaluate_alerts,
)


def _snapshot(
    *,
    requests: int = 100,
    errors: int = 0,
    p95_ms: float = 100.0,
    backup_age: float | None = 3600,
    backup_status: str = "ok",
    disk: float | None = 50.0,
    db_per_minute: float = 0.0,
    backlog: int = 100,
    stalled: list[str] | None = None,
    failed: list[dict] | None = None,
    archive_percent: float = 10.0,
    services: dict[str, bool] | None = None,
) -> dict:
    return {
        "http": {
            "windows": {
                "5m": {
                    "requests": requests,
                    "errors_5xx": errors,
                    "error_rate": errors / requests if requests else 0.0,
                    "p95_ms": p95_ms,
                    "p50_ms": p95_ms / 2,
                    "p99_ms": p95_ms * 1.2,
                }
            }
        },
        "db": {"per_minute_5m": db_per_minute, "errors_5m": db_per_minute * 5},
        "backup": {
            "configured": backup_age is not None,
            "status": backup_status,
            "age_seconds": backup_age,
            "last_error": "restic failed" if backup_status == "failed" else None,
        },
        "disk": {"used_percent": disk, "path": "/"},
        "crawler": {
            "backlog": backlog,
            "stalled": stalled or [],
            "failed": failed or [],
        },
        "media": {
            "archive_usage_percent": archive_percent,
            "image_cache_bytes": 1024,
        },
        "services": services or {"catalog": True},
    }


def test_http_thresholds() -> None:
    alerts = evaluate_alerts(observability=_snapshot(errors=5, p95_ms=2500))
    keys = {alert.key for alert in alerts}
    assert "http_5xx_rate" in keys
    assert "http_p95_latency" in keys

    quiet = evaluate_alerts(observability=_snapshot(errors=1, p95_ms=500))
    assert not {alert.key for alert in quiet} & {"http_5xx_rate", "http_p95_latency"}

    tiny = evaluate_alerts(observability=_snapshot(requests=10, errors=5, p95_ms=5000))
    assert not {alert.key for alert in tiny} & {"http_5xx_rate", "http_p95_latency"}


def test_backup_disk_db_crawler_and_media_alerts() -> None:
    alerts = evaluate_alerts(
        observability=_snapshot(
            backup_age=27 * 3600,
            disk=95.0,
            db_per_minute=6.0,
            backlog=12_000,
            stalled=["remanga"],
            failed=[{"source": "mangalib", "mode": "full", "last_error": "403"}],
            archive_percent=85.0,
            services={"catalog": False},
        )
    )
    keys = {alert.key for alert in alerts}
    assert "backup_stale" in keys
    assert "disk_usage" in keys
    assert "sqlite_lock_rate" in keys
    assert "crawler_backlog" in keys
    assert "crawler_stalled:remanga" in keys
    assert "crawler_failed:mangalib:full" in keys
    assert "archive_usage" in keys
    assert "service_down:catalog" in keys

    failed_backup = evaluate_alerts(
        observability=_snapshot(backup_age=3600, backup_status="failed")
    )
    assert any(alert.key == "backup_failed" for alert in failed_backup)

    warning_disk = evaluate_alerts(observability=_snapshot(disk=85.0))
    assert any(
        alert.key == "disk_usage" and alert.severity == "warning"
        for alert in warning_disk
    )


def test_thresholds_are_configurable() -> None:
    thresholds = AlertThresholds(http_5xx_rate=0.5, http_p95_ms=10_000)
    alerts = evaluate_alerts(
        observability=_snapshot(errors=5, p95_ms=2500), thresholds=thresholds
    )
    assert not {alert.key for alert in alerts} & {"http_5xx_rate", "http_p95_latency"}


def test_dedupe_cooldown_and_escalation() -> None:
    dedupe = AlertDeduplicator(cooldown_seconds=100)
    warning = Alert(key="disk_usage", severity="warning", summary="Диск 85%")
    critical = Alert(key="disk_usage", severity="critical", summary="Диск 95%")

    assert dedupe.select([warning], now=1000) == [warning]
    assert dedupe.select([warning], now=1050) == []
    # Severity escalation bypasses the cooldown.
    assert dedupe.select([critical], now=1060) == [critical]
    assert dedupe.select([critical], now=1070) == []
    # Cooldown still expires for an unchanged severity.
    assert dedupe.select([critical], now=1200) == [critical]

    restored = dedupe.select([], now=1300)
    assert len(restored) == 1
    assert restored[0].severity == "info"
    assert restored[0].key == "recovered:disk_usage"
    assert dedupe.select([], now=1400) == []

    # After recovery a new occurrence is sent immediately again.
    assert dedupe.select([warning], now=1500) == [warning]


def test_dedupe_does_not_recover_when_source_is_unavailable() -> None:
    dedupe = AlertDeduplicator(cooldown_seconds=100)
    alert = Alert(key="service_down:catalog", severity="critical", summary="down")
    assert dedupe.select([alert], now=1000) == [alert]

    # A failed metrics fetch must not look like a recovery of every alert.
    assert dedupe.select([], now=1010, recover_missing=False) == []
    assert "service_down:catalog" in dedupe.entries

    # When the source returns and the condition is really gone, recover once.
    recovered = dedupe.select([], now=1020)
    assert [item.key for item in recovered] == ["recovered:service_down:catalog"]


def test_dedupe_state_roundtrip() -> None:
    dedupe = AlertDeduplicator(cooldown_seconds=100)
    alert = Alert(key="backup_stale", severity="critical", summary="Нет бэкапа")
    assert dedupe.select([alert], now=1000) == [alert]

    restored = AlertDeduplicator()
    restored.load(dedupe.dump())
    assert restored.select([alert], now=1050) == []
