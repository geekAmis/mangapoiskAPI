"""Gateway-side observability collector.

The gateway is the only public entry point, so it is the natural place to
aggregate dependency health, crawler backlog/ETA, media usage and backup age.
Upstream calls are cached for ``OBSERVABILITY_REFRESH_SECONDS`` (30 s by
default); ``/metrics`` and the admin panel read the last snapshot instead of
fanning out on every scrape.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from manga_common.alerts import AlertThresholds, evaluate_alerts
from manga_common.metrics import metrics

logger = logging.getLogger(__name__)

DB_COUNTER_KEYS = (
    "errors_total",
    "retries_total",
    "exhausted_total",
    "recovered_total",
    "errors_1m",
    "errors_5m",
    "retries_5m",
)


def merge_db_snapshots(snapshots: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Sum SQLite lock counters from every service process.

    Each service has its own in-process registry, so the gateway aggregates the
    ``db`` section of their ``/metrics?format=json`` responses.  The original
    per-service values stay available under ``by_service`` for the admin panel
    and for debugging which writer is contended.
    """

    totals: dict[str, Any] = {key: 0 for key in DB_COUNTER_KEYS}
    by_service: dict[str, dict[str, Any]] = {}
    for name, payload in snapshots.items():
        if not isinstance(payload, dict):
            continue
        stats = {key: int(payload.get(key) or 0) for key in DB_COUNTER_KEYS}
        stats["per_minute_5m"] = round(float(payload.get("per_minute_5m") or 0.0), 3)
        by_service[name] = stats
        for key in DB_COUNTER_KEYS:
            totals[key] += stats[key]
    totals["per_minute_5m"] = round(
        sum(stats["per_minute_5m"] for stats in by_service.values()), 3
    )
    totals["by_service"] = by_service
    return totals


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


def read_backup_status(paths: list[Path], *, now: datetime | None = None) -> dict[str, Any]:
    """Read the no-secret status file written by mangapoisk-backup.sh."""

    current = now or datetime.now(UTC)
    payload: dict[str, Any] | None = None
    used_path: Path | None = None
    for path in paths:
        try:
            if path.is_file():
                payload = json.loads(path.read_text(encoding="utf-8"))
                used_path = path
                break
        except (OSError, ValueError) as exc:
            logger.warning("backup status file %s is unreadable: %s", path, exc)
    if not isinstance(payload, dict):
        return {
            "configured": False,
            "status": "missing",
            "last_success_at": None,
            "last_attempt_at": None,
            "age_seconds": None,
            "last_error": None,
            "path": None,
        }
    last_success = _parse_dt(payload.get("last_success_at"))
    last_attempt = _parse_dt(payload.get("last_attempt_at"))
    age = (current - last_success).total_seconds() if last_success else None
    return {
        "configured": True,
        "status": str(payload.get("status") or "unknown"),
        "last_success_at": _iso(last_success),
        "last_attempt_at": _iso(last_attempt),
        "age_seconds": round(age, 1) if age is not None else None,
        "last_error": payload.get("last_error"),
        "path": str(used_path) if used_path else None,
        "host": payload.get("host"),
        "duration_seconds": payload.get("duration_seconds"),
    }


def _backup_candidates(configured: str) -> list[Path]:
    candidates = [Path(configured)]
    production = Path("/var/lib/mangapoisk-backup/status.json")
    if production not in candidates:
        candidates.append(production)
    return candidates


def _disk_snapshot(path: str | None = None) -> dict[str, Any]:
    target = path or "/"
    if not Path(target).exists():
        target = str(Path.cwd().anchor or Path.cwd())
    try:
        usage = shutil.disk_usage(target)
    except OSError as exc:
        return {"path": target, "used_percent": None, "free_bytes": None, "error": str(exc)}
    used_percent = (usage.used / usage.total * 100) if usage.total else 0.0
    return {
        "path": target,
        "used_percent": round(used_percent, 2),
        "free_bytes": usage.free,
        "total_bytes": usage.total,
    }


def _crawler_snapshot(
    catalog_stats: dict[str, Any],
    crawl_states: list[dict[str, Any]],
    *,
    now: datetime,
    stall_minutes: int,
) -> dict[str, Any]:
    backlog = int(catalog_stats.get("pending_enrichment") or catalog_stats.get("pending") or 0)
    backlog_by_source: dict[str, int] = {}
    raw_sources = catalog_stats.get("sources")
    if isinstance(raw_sources, list):
        for item in raw_sources:
            if isinstance(item, dict) and item.get("source"):
                backlog_by_source[str(item["source"])] = int(item.get("pending") or 0)

    sources: list[dict[str, Any]] = []
    stalled: list[str] = []
    failed: list[dict[str, Any]] = []
    for raw in crawl_states:
        if not isinstance(raw, dict):
            continue
        source = str(raw.get("source") or "")
        mode = str(raw.get("mode") or "")
        if not source or mode not in {"full", "incremental"}:
            continue
        status = str(raw.get("status") or "pending")
        last_run = _parse_dt(raw.get("last_run_at"))
        total_pages = int(raw["total_pages"]) if raw.get("total_pages") is not None else None
        page = int(raw.get("page") or 0)
        progress = (
            round(min(100.0, page / total_pages * 100), 1) if total_pages else None
        )
        is_stalled = bool(
            status == "running"
            and last_run is not None
            and now - last_run > timedelta(minutes=stall_minutes)
        )
        if is_stalled and source not in stalled:
            stalled.append(source)
        if status == "failed":
            failed.append(
                {
                    "source": source,
                    "mode": mode,
                    "last_error": raw.get("last_error"),
                }
            )
        sources.append(
            {
                "source": source,
                "mode": mode,
                "status": status,
                "page": page,
                "total_pages": total_pages,
                "progress_percent": progress,
                "eta_seconds": raw.get("eta_seconds"),
                "last_run_at": _iso(last_run),
                "next_run_at": _iso(_parse_dt(raw.get("next_run_at"))),
                "last_error": raw.get("last_error"),
                "stalled": is_stalled,
            }
        )
    return {
        "backlog": backlog,
        "backlog_by_source": backlog_by_source,
        "sources": sources,
        "stalled": stalled,
        "failed": failed,
    }


def _media_snapshot(media_stats: dict[str, Any]) -> dict[str, Any]:
    archives = media_stats.get("archives")
    archives = archives if isinstance(archives, dict) else {}
    image = media_stats.get("image_cache")
    image = image if isinstance(image, dict) else {}
    image_bytes = int(
        media_stats.get("image_cache_bytes") or image.get("used_bytes") or 0
    )
    return {
        "archive_usage_percent": float(archives.get("usage_percent") or 0.0),
        "archive_done_bytes": int(archives.get("done_bytes") or 0),
        "archive_cap_bytes": int(archives.get("cap_bytes") or 0),
        "archive_done": int(archives.get("done") or 0),
        "archive_failed": int(archives.get("failed") or 0),
        "archive_pending": int(archives.get("pending") or 0),
        "image_cache_bytes": image_bytes,
        "image_cache_usage_percent": float(image.get("usage_percent") or 0.0),
        "image_cache_files": int(image.get("files") or 0),
        "warnings": list(media_stats.get("warnings") or []),
    }


def build_observability_snapshot(
    *,
    metrics_snapshot: dict[str, Any],
    services: dict[str, bool],
    catalog_stats: dict[str, Any],
    crawl_states: list[dict[str, Any]],
    media_stats: dict[str, Any],
    backup: dict[str, Any],
    disk: dict[str, Any],
    thresholds: AlertThresholds,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(UTC)
    crawler = _crawler_snapshot(
        catalog_stats,
        crawl_states,
        now=current,
        stall_minutes=thresholds.crawler_stall_minutes,
    )
    media = _media_snapshot(media_stats)
    snapshot = {
        "generated_at": _iso(current),
        "http": metrics_snapshot.get("http", {}),
        "db": metrics_snapshot.get("db", {}),
        "services": services,
        "crawler": crawler,
        "media": media,
        "backup": backup,
        "disk": disk,
    }
    snapshot["alerts"] = [
        alert.as_dict() for alert in evaluate_alerts(observability=snapshot, thresholds=thresholds)
    ]
    return snapshot


class GatewayObservabilityCollector:
    def __init__(self, app, settings) -> None:  # type: ignore[no-untyped-def]
        self.app = app
        self.settings = settings
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        # ``/metrics?format=json`` on the gateway returns the full aggregated
        # snapshot, not only the gateway process's counters.  The watchdog and
        # small installations use this as their single JSON source.
        self.app.state.metrics_snapshot_provider = lambda: getattr(
            self.app.state, "observability_snapshot", None
        )
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.refresh()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("observability refresh failed")
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=max(5, self.settings.observability_refresh_seconds),
                )
            except TimeoutError:
                continue

    async def refresh(self) -> dict[str, Any]:
        state = self.app.state
        clients = {
            "catalog": getattr(state, "catalog", None),
            "parser": getattr(state, "parser", None),
            "library": getattr(state, "library", None),
            "media": getattr(state, "media", None),
            "comments": getattr(state, "comments", None),
            "notifier": getattr(state, "notifier", None),
            "control": getattr(state, "control", None),
        }
        health_results = await asyncio.gather(
            *(self._health(name, client) for name, client in clients.items()),
            return_exceptions=True,
        )
        services = {
            name: bool(result)
            for name, result in zip(clients, health_results, strict=True)
        }
        catalog_stats, crawl_states, media_stats = await asyncio.gather(
            self._catalog_stats(),
            self._crawl_states(),
            self._media_stats(),
        )
        metric_clients = {
            name: clients[name]
            for name in ("catalog", "library", "comments", "notifier", "media", "control")
        }
        metric_payloads = await asyncio.gather(
            *(self._service_metrics(name, client) for name, client in metric_clients.items()),
            return_exceptions=True,
        )
        local_metrics = metrics.snapshot()
        db_snapshots: dict[str, dict[str, Any]] = {"gateway": local_metrics.get("db", {})}
        for name, payload in zip(metric_clients, metric_payloads, strict=True):
            if not isinstance(payload, dict):
                continue
            db = payload.get("db")
            if isinstance(db, dict):
                db_snapshots[name] = db
        local_metrics["db"] = merge_db_snapshots(db_snapshots)
        thresholds = AlertThresholds(
            http_5xx_rate=self.settings.alert_5xx_rate,
            http_p95_ms=self.settings.alert_p95_ms,
            backup_age_hours=self.settings.alert_backup_age_hours,
            db_lock_per_minute=self.settings.alert_db_lock_per_minute,
            enrichment_backlog=self.settings.alert_enrichment_backlog,
            archive_usage_percent=self.settings.alert_archive_usage_percent,
        )
        backup = read_backup_status(_backup_candidates(self.settings.backup_status_file))
        disk = _disk_snapshot()
        snapshot = build_observability_snapshot(
            metrics_snapshot=local_metrics,
            services=services,
            catalog_stats=catalog_stats,
            crawl_states=crawl_states,
            media_stats=media_stats,
            backup=backup,
            disk=disk,
            thresholds=thresholds,
        )
        self.app.state.observability_snapshot = snapshot
        self._publish_gauges(snapshot)
        return snapshot

    async def _health(self, name: str, client: Any) -> bool:
        if client is None:
            return False
        try:
            response = await client.client.get("/health", timeout=3.0)
            return response.status_code == 200
        except Exception:
            return False

    async def _service_metrics(self, name: str, client: Any) -> dict[str, Any]:
        """Read a service's own JSON registry to aggregate SQLite lock counters."""

        if client is None:
            return {}
        headers: dict[str, str] = {}
        if self.settings.metrics_token:
            headers["X-Metrics-Token"] = self.settings.metrics_token
        try:
            response = await client.client.get(
                "/metrics",
                params={"format": "json"},
                headers=headers,
                timeout=3.0,
            )
            if response.status_code != 200:
                return {}
            payload = response.json()
            return payload if isinstance(payload, dict) else {}
        except Exception as exc:
            logger.debug("observability: %s metrics unavailable: %s", name, exc)
            return {}

    async def _catalog_stats(self) -> dict[str, Any]:
        catalog = getattr(self.app.state, "catalog", None)
        if catalog is None:
            return {}
        try:
            data = await catalog.stats()
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.warning("observability: catalog stats unavailable: %s", exc)
            return {}

    async def _crawl_states(self) -> list[dict[str, Any]]:
        catalog = getattr(self.app.state, "catalog", None)
        if catalog is None:
            return []
        try:
            return await catalog.crawl_states()
        except Exception as exc:
            logger.warning("observability: crawl states unavailable: %s", exc)
            return []

    async def _media_stats(self) -> dict[str, Any]:
        media = getattr(self.app.state, "media", None)
        if media is None:
            return {}
        try:
            data = await media.stats()
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.warning("observability: media stats unavailable: %s", exc)
            return {}

    def _publish_gauges(self, snapshot: dict[str, Any]) -> None:
        for name, healthy in snapshot["services"].items():
            metrics.set("mangapoisk_service_up", 1 if healthy else 0, service=name)
        for name, db_stats in snapshot["db"].get("by_service", {}).items():
            metrics.set(
                "mangapoisk_upstream_sqlite_lock_errors_total",
                float(db_stats.get("errors_total") or 0),
                service=name,
            )
            metrics.set(
                "mangapoisk_upstream_sqlite_lock_errors_5m",
                float(db_stats.get("errors_5m") or 0),
                service=name,
            )
            metrics.set(
                "mangapoisk_upstream_sqlite_lock_retries_total",
                float(db_stats.get("retries_total") or 0),
                service=name,
            )
        crawler = snapshot["crawler"]
        metrics.set("mangapoisk_crawler_backlog", crawler["backlog"])
        for source, value in crawler["backlog_by_source"].items():
            metrics.set("mangapoisk_crawler_backlog_source", value, source=source)
        stalled = set(crawler["stalled"])
        failed = {(item["source"], item["mode"]) for item in crawler["failed"]}
        for item in crawler["sources"]:
            source = item["source"]
            mode = item["mode"]
            progress = item["progress_percent"]
            if progress is not None:
                metrics.set(
                    "mangapoisk_crawler_progress_ratio",
                    round(progress / 100, 4),
                    source=source,
                    mode=mode,
                )
            if item["eta_seconds"] is not None:
                metrics.set(
                    "mangapoisk_crawler_eta_seconds",
                    float(item["eta_seconds"]),
                    source=source,
                    mode=mode,
                )
            metrics.set(
                "mangapoisk_crawler_stalled",
                1 if source in stalled else 0,
                source=source,
            )
            metrics.set(
                "mangapoisk_crawler_failed",
                1 if (source, mode) in failed else 0,
                source=source,
                mode=mode,
            )
        media = snapshot["media"]
        metrics.set(
            "mangapoisk_media_archive_usage_ratio",
            round(media["archive_usage_percent"] / 100, 4),
        )
        metrics.set("mangapoisk_media_archive_bytes", media["archive_done_bytes"])
        metrics.set("mangapoisk_media_cache_bytes", media["image_cache_bytes"])
        metrics.set(
            "mangapoisk_media_cache_usage_ratio",
            round(media["image_cache_usage_percent"] / 100, 4),
        )
        backup = snapshot["backup"]
        metrics.set(
            "mangapoisk_backup_status_configured", 1 if backup["configured"] else 0
        )
        metrics.set(
            "mangapoisk_backup_status_ok",
            1 if backup["configured"] and backup["status"] == "ok" else 0,
        )
        # -1 means "unknown" (no status file or no successful run yet); the
        # separate configured/ok gauges distinguish that from a fresh backup.
        metrics.set(
            "mangapoisk_backup_age_seconds",
            float(backup["age_seconds"]) if backup["age_seconds"] is not None else -1.0,
        )
        last_success = _parse_dt(backup.get("last_success_at"))
        metrics.set(
            "mangapoisk_backup_last_success_timestamp_seconds",
            last_success.timestamp() if last_success is not None else 0.0,
        )
        disk = snapshot["disk"]
        if disk.get("used_percent") is not None:
            metrics.set(
                "mangapoisk_disk_used_ratio", round(float(disk["used_percent"]) / 100, 4)
            )
            metrics.set("mangapoisk_disk_free_bytes", float(disk["free_bytes"] or 0))
        severity_counts: dict[str, int] = {}
        for alert in snapshot["alerts"]:
            severity_counts[alert["severity"]] = severity_counts.get(alert["severity"], 0) + 1
        for severity in ("warning", "high", "critical"):
            metrics.set(
                "mangapoisk_alerts_active",
                severity_counts.get(severity, 0),
                severity=severity,
            )
