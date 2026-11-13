#!/usr/bin/env python3
"""MangaPoisk Reborn health watchdog.

Runs from a systemd timer every minute (or from ``mangapoisk-alert@.service`` on
a unit failure) and posts deduplicated alerts through the existing notifier bot.
Secrets are read from the process environment (systemd ``EnvironmentFile``);
they are never written to the state file, logs or Telegram text.

Checks:
  * service health from the gateway's cached observability snapshot;
  * 5xx rate, p95 latency and SQLite lock rate;
  * disk usage;
  * backup freshness/status from mangapoisk-backup.sh status.json;
  * crawler stalled/failed and enrichment backlog.

Alerts are deduplicated per key with a one-hour cooldown.  A severity escalation
bypasses the cooldown, and a recovered condition produces one informational
message.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:  # POSIX only; tests and development on Windows can skip the lock.
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None

from manga_common.alerts import Alert, AlertDeduplicator, AlertThresholds, evaluate_alerts


@dataclass(frozen=True)
class WatchdogSettings:
    gateway_metrics_url: str
    notifier_url: str
    notify_path: str
    internal_token: str | None
    metrics_token: str | None
    state_file: Path
    backup_status_file: Path
    backup_required: bool
    disk_path: str
    cooldown_seconds: float
    request_timeout: float
    dry_run: bool


def load_settings() -> WatchdogSettings:
    def env(name: str, default: str) -> str:
        return os.environ.get(name, default).strip()

    return WatchdogSettings(
        gateway_metrics_url=env(
            "WATCHDOG_GATEWAY_METRICS_URL", "http://127.0.0.1:8100/metrics?format=json"
        ),
        notifier_url=env("NOTIFIER_URL", "http://127.0.0.1:8106").rstrip("/"),
        notify_path=env("WATCHDOG_NOTIFY_PATH", "/internal/notify/alert"),
        internal_token=os.environ.get("INTERNAL_TOKEN") or None,
        metrics_token=os.environ.get("WATCHDOG_METRICS_TOKEN")
        or os.environ.get("METRICS_TOKEN")
        or None,
        state_file=Path(
            env("WATCHDOG_STATE_FILE", "/var/lib/mangapoisk-watchdog/state.json")
        ),
        backup_status_file=Path(
            env(
                "WATCHDOG_BACKUP_STATUS_FILE",
                env("BACKUP_STATUS_FILE", "/var/lib/mangapoisk-backup/status.json"),
            )
        ),
        backup_required=env("WATCHDOG_BACKUP_REQUIRED", "1") not in {"0", "false", "no"},
        disk_path=env("WATCHDOG_DISK_PATH", "/"),
        cooldown_seconds=float(env("WATCHDOG_COOLDOWN_SECONDS", "3600")),
        request_timeout=float(env("WATCHDOG_REQUEST_TIMEOUT_SECONDS", "10")),
        dry_run=env("WATCHDOG_DRY_RUN", "0") in {"1", "true", "yes"},
    )


def fetch_json(
    url: str,
    *,
    token: str | None,
    metrics_token: str | None = None,
    timeout: float,
) -> dict[str, Any]:
    """Fetch a JSON snapshot without ever logging the tokens.

    ``token`` is the internal service token (gateway admin/health helpers);
    ``metrics_token`` is the optional ``METRICS_TOKEN`` that protects
    ``/metrics`` when it is exposed beyond loopback.
    """

    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    if token:
        request.add_header("X-Internal-Token", token)
    if metrics_token:
        request.add_header("X-Metrics-Token", metrics_token)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def disk_snapshot(path: str) -> dict[str, Any]:
    target = path
    if not Path(target).exists():
        target = str(Path.cwd().anchor or Path.cwd())
    try:
        usage = shutil.disk_usage(target)
    except OSError as exc:
        return {"path": target, "used_percent": None, "error": str(exc)}
    return {
        "path": target,
        "used_percent": round(usage.used / usage.total * 100, 2) if usage.total else 0.0,
        "free_bytes": usage.free,
        "total_bytes": usage.total,
    }


def backup_snapshot(path: Path, *, required: bool, now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(UTC)
    payload = read_json(path)
    if not payload:
        return {
            "configured": required,
            "status": "missing",
            "last_success_at": None,
            "last_attempt_at": None,
            "age_seconds": None,
            "last_error": None,
        }
    last_success = payload.get("last_success_at")
    age = None
    if isinstance(last_success, str) and last_success:
        try:
            parsed = datetime.fromisoformat(last_success.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            age = (current - parsed).total_seconds()
        except ValueError:
            age = None
    if age is None:
        # No successful run recorded yet.  Fall back to the status file's mtime
        # so a backup that never completes (or a stuck "running" state) still
        # becomes stale after 26 hours instead of staying silent forever.
        try:
            age = (current - datetime.fromtimestamp(path.stat().st_mtime, UTC)).total_seconds()
        except OSError:
            age = None
    return {
        "configured": True,
        "status": str(payload.get("status") or "unknown"),
        "last_success_at": last_success,
        "last_attempt_at": payload.get("last_attempt_at"),
        "age_seconds": round(age, 1) if age is not None else None,
        "last_error": payload.get("last_error"),
        "host": payload.get("host"),
    }


def collect_alerts(
    settings: WatchdogSettings,
    *,
    now: datetime | None = None,
) -> list[Alert]:
    current = now or datetime.now(UTC)
    alerts: list[Alert] = []
    snapshot: dict[str, Any] = {}
    try:
        snapshot = fetch_json(
            settings.gateway_metrics_url,
            token=settings.internal_token,
            metrics_token=settings.metrics_token,
            timeout=settings.request_timeout,
        )
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        alerts.append(
            Alert(
                key="gateway_metrics_unavailable",
                severity="critical",
                summary="Метрики gateway недоступны",
                # Do not echo the request URL: a custom WATCHDOG_GATEWAY_METRICS_URL
                # could contain a token in its query string.
                details=f"{type(exc).__name__}: {getattr(exc, 'reason', '')}"[:300],
            )
        )
    if not snapshot and not any(
        alert.key == "gateway_metrics_unavailable" for alert in alerts
    ):
        alerts.append(
            Alert(
                key="gateway_metrics_unavailable",
                severity="critical",
                summary="Метрики gateway недоступны",
                details="Пустой JSON-снимок; проверьте версию gateway и /metrics.",
            )
        )

    thresholds = AlertThresholds()
    if snapshot:
        snapshot["disk"] = disk_snapshot(settings.disk_path)
        alerts.extend(evaluate_alerts(observability=snapshot, thresholds=thresholds))

    backup = backup_snapshot(
        settings.backup_status_file, required=settings.backup_required, now=current
    )
    if settings.backup_required and backup["status"] == "missing":
        alerts.append(
            Alert(
                key="backup_missing",
                severity="critical",
                summary="Статус бэкапа отсутствует",
                details=f"Нет файла {settings.backup_status_file}",
            )
        )
    elif backup["configured"]:
        backup_view = dict(snapshot)
        backup_view["backup"] = backup
        alerts.extend(evaluate_alerts(observability=backup_view, thresholds=thresholds))

    if not snapshot:
        # The gateway snapshot also carries disk usage; when it is unavailable
        # still evaluate the local filesystem so a full disk is never missed.
        alerts.extend(
            evaluate_alerts(
                observability={"disk": disk_snapshot(settings.disk_path)},
                thresholds=thresholds,
            )
        )

    # Deduplicate by key while keeping the most severe occurrence.
    by_key: dict[str, Alert] = {}
    for alert in alerts:
        previous = by_key.get(alert.key)
        if previous is None or _severity_rank(alert.severity) > _severity_rank(
            previous.severity
        ):
            by_key[alert.key] = alert
    return list(by_key.values())


def _severity_rank(severity: str) -> int:
    return {"info": 0, "warning": 1, "high": 2, "critical": 3}.get(severity, 0)


def load_state(path: Path, *, cooldown_seconds: float = 3600.0) -> AlertDeduplicator:
    deduplicator = AlertDeduplicator(cooldown_seconds=cooldown_seconds)
    deduplicator.load(read_json(path))
    return deduplicator


def save_state(path: Path, deduplicator: AlertDeduplicator) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".watchdog-", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(deduplicator.dump(), handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def send_alert(settings: WatchdogSettings, alert: Alert) -> bool:
    text = alert.as_text()
    if settings.dry_run:
        print(text)
        return True
    if not settings.internal_token:
        print("INTERNAL_TOKEN is not set; cannot call notifier", file=sys.stderr)
        return False
    body = json.dumps(
        {"text": text[:4096], "parse_mode": None, "disable_preview": True}
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{settings.notifier_url}{settings.notify_path}",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Internal-Token": settings.internal_token,
        },
    )
    try:
        with urllib.request.urlopen(
            request, timeout=settings.request_timeout
        ) as response:
            raw = response.read()
        payload = json.loads(raw.decode("utf-8")) if raw else {}
        # The notifier returns {"sent": false} when Telegram is not configured;
        # treat that as a delivery failure so the next tick retries instead of
        # suppressing the alert for the whole cooldown.
        return bool(payload.get("sent")) if isinstance(payload, dict) else False
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        print(f"notifier delivery failed: {type(exc).__name__}", file=sys.stderr)
        return False


def _lock_state(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(".lock")
    handle = open(lock_path, "a+", encoding="utf-8")  # noqa: SIM115
    if fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    return handle


def run_check(settings: WatchdogSettings) -> int:
    lock = _lock_state(settings.state_file)
    try:
        deduplicator = load_state(
            settings.state_file, cooldown_seconds=settings.cooldown_seconds
        )
        alerts = collect_alerts(settings)
        metrics_unavailable = any(
            alert.key == "gateway_metrics_unavailable" for alert in alerts
        )
        selected = deduplicator.select(
            alerts, recover_missing=not metrics_unavailable
        )
        failed = 0
        for alert in selected:
            if not send_alert(settings, alert):
                failed += 1
                # Do not remember an undelivered alert: retry it on the next
                # timer tick instead of suppressing it for the cooldown.
                deduplicator.entries.pop(alert.key, None)
        if not settings.dry_run:
            save_state(settings.state_file, deduplicator)
        return 1 if failed else 0
    finally:
        lock.close()


def run_service_failed(settings: WatchdogSettings, unit: str) -> int:
    lock = _lock_state(settings.state_file)
    try:
        deduplicator = load_state(
            settings.state_file, cooldown_seconds=settings.cooldown_seconds
        )
        alert = Alert(
            key=f"service_failed:{unit}",
            severity="critical",
            summary=f"Systemd unit {unit} failed",
            details="Проверьте systemctl status и journalctl -u.",
        )
        # This is a one-shot failed-unit notification, not a full health
        # snapshot: do not mark every other active alert as recovered.
        selected = deduplicator.select([alert], recover_missing=False)
        delivered = True
        for item in selected:
            if not send_alert(settings, item):
                delivered = False
                deduplicator.entries.pop(item.key, None)
        if not settings.dry_run:
            save_state(settings.state_file, deduplicator)
        return 0 if delivered else 1
    finally:
        lock.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--service-failed",
        metavar="UNIT",
        help="send a one-shot alert for a failed systemd unit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print alerts instead of sending them",
    )
    args = parser.parse_args(argv)
    settings = load_settings()
    if args.dry_run:
        settings = WatchdogSettings(**{**settings.__dict__, "dry_run": True})
    if args.service_failed:
        return run_service_failed(settings, args.service_failed)
    return run_check(settings)


if __name__ == "__main__":
    sys.exit(main())
