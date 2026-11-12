"""Alert rules and dedupe/cooldown state shared by the gateway and watchdog.

Thresholds follow ``docs/OPS.md`` section 5.  The module is intentionally pure:
the gateway uses it for the admin panel and the systemd watchdog uses it before
sending a Telegram message.  No tokens or URLs are ever included in alert text.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

SEVERITY_RANK = {"info": 0, "warning": 1, "high": 2, "critical": 3}


@dataclass(frozen=True)
class AlertThresholds:
    http_5xx_rate: float = 0.02
    http_p95_ms: float = 2000.0
    disk_warning_percent: float = 80.0
    disk_critical_percent: float = 90.0
    backup_age_hours: float = 26.0
    crawler_stall_minutes: int = 30
    db_lock_per_minute: float = 5.0
    enrichment_backlog: int = 10_000
    archive_usage_percent: float = 80.0
    media_cache_bytes: int = 10 * 1024**3


DEFAULT_THRESHOLDS = AlertThresholds()


@dataclass(frozen=True)
class Alert:
    key: str
    severity: str
    summary: str
    details: str = ""
    value: float | int | str | None = None
    threshold: float | int | str | None = None

    @property
    def fingerprint(self) -> str:
        return f"{self.key}:{self.severity}:{self.value}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "severity": self.severity,
            "summary": self.summary,
            "details": self.details,
            "value": self.value,
            "threshold": self.threshold,
        }

    def as_text(self) -> str:
        lines = [f"[{self.severity.upper()}] {self.summary}"]
        if self.details:
            lines.append(self.details)
        if self.value is not None and self.threshold is not None:
            lines.append(f"value={self.value} threshold={self.threshold}")
        return "\n".join(lines)


def _window(snapshot: dict[str, Any], name: str = "5m") -> dict[str, Any]:
    http = snapshot.get("http")
    if not isinstance(http, dict):
        return {}
    windows = http.get("windows")
    if not isinstance(windows, dict):
        return {}
    value = windows.get(name)
    return value if isinstance(value, dict) else {}


def evaluate_alerts(
    *,
    observability: dict[str, Any],
    thresholds: AlertThresholds = DEFAULT_THRESHOLDS,
) -> list[Alert]:
    """Evaluate one observability snapshot and return active alerts.

    ``observability`` is the payload exposed by the gateway admin endpoint.  All
    sections are optional so a partial outage still produces useful alerts.
    """

    alerts: list[Alert] = []
    five = _window(observability, "5m")
    requests = int(five.get("requests") or 0)
    error_rate = float(five.get("error_rate") or 0.0)
    if requests >= 20 and error_rate > thresholds.http_5xx_rate:
        alerts.append(
            Alert(
                key="http_5xx_rate",
                severity="high",
                summary=f"Доля 5xx за 5 минут {error_rate * 100:.1f}%",
                details=f"{int(five.get('errors_5xx') or 0)} из {requests} запросов",
                value=round(error_rate, 4),
                threshold=thresholds.http_5xx_rate,
            )
        )

    p95 = float(five.get("p95_ms") or 0.0)
    if requests >= 20 and p95 > thresholds.http_p95_ms:
        alerts.append(
            Alert(
                key="http_p95_latency",
                severity="high",
                summary=f"p95 latency за 5 минут {p95:.0f} мс",
                details=f"{requests} запросов в окне",
                value=round(p95, 1),
                threshold=thresholds.http_p95_ms,
            )
        )

    backup = observability.get("backup")
    if isinstance(backup, dict) and backup.get("configured"):
        age = backup.get("age_seconds")
        status = str(backup.get("status") or "")
        if status == "failed":
            alerts.append(
                Alert(
                    key="backup_failed",
                    severity="critical",
                    summary="Последний запуск бэкапа завершился ошибкой",
                    details=str(backup.get("last_error") or "")[:300],
                    value=status,
                )
            )
        elif age is not None and float(age) > thresholds.backup_age_hours * 3600:
            alerts.append(
                Alert(
                    key="backup_stale",
                    severity="critical",
                    summary=f"Бэкапа нет {float(age) / 3600:.1f} ч",
                    details="Проверьте mangapoisk-backup.timer и restic snapshots.",
                    value=round(float(age) / 3600, 1),
                    threshold=thresholds.backup_age_hours,
                )
            )

    disk = observability.get("disk")
    if isinstance(disk, dict) and disk.get("used_percent") is not None:
        used = float(disk["used_percent"])
        if used >= thresholds.disk_critical_percent:
            alerts.append(
                Alert(
                    key="disk_usage",
                    severity="critical",
                    summary=f"Диск заполнен на {used:.0f}%",
                    details=str(disk.get("path") or "/"),
                    value=round(used, 1),
                    threshold=thresholds.disk_critical_percent,
                )
            )
        elif used >= thresholds.disk_warning_percent:
            alerts.append(
                Alert(
                    key="disk_usage",
                    severity="warning",
                    summary=f"Диск заполнен на {used:.0f}%",
                    details=str(disk.get("path") or "/"),
                    value=round(used, 1),
                    threshold=thresholds.disk_warning_percent,
                )
            )

    db = observability.get("db")
    if isinstance(db, dict):
        per_minute = float(db.get("per_minute_5m") or 0.0)
        if per_minute > thresholds.db_lock_per_minute:
            alerts.append(
                Alert(
                    key="sqlite_lock_rate",
                    severity="high",
                    summary=f"SQLite lock errors {per_minute:.1f}/мин",
                    details=f"errors_5m={db.get('errors_5m', 0)} retries_5m={db.get('retries_5m', 0)}",
                    value=round(per_minute, 1),
                    threshold=thresholds.db_lock_per_minute,
                )
            )

    crawler = observability.get("crawler")
    if isinstance(crawler, dict):
        backlog = int(crawler.get("backlog") or 0)
        if backlog > thresholds.enrichment_backlog:
            alerts.append(
                Alert(
                    key="crawler_backlog",
                    severity="warning",
                    summary=f"Очередь обогащения {backlog} тайтлов",
                    details="Проверьте scheduler/enrichment concurrency.",
                    value=backlog,
                    threshold=thresholds.enrichment_backlog,
                )
            )
        for source in crawler.get("stalled") or []:
            alerts.append(
                Alert(
                    key=f"crawler_stalled:{source}",
                    severity="high",
                    summary=f"Краулер {source} не обновлял прогресс > {thresholds.crawler_stall_minutes} мин",
                    details="Проверьте scheduler, cookie и последний last_error.",
                    value=source,
                )
            )
        for item in crawler.get("failed") or []:
            if isinstance(item, dict):
                source = str(item.get("source") or "unknown")
                mode = str(item.get("mode") or "full")
                alerts.append(
                    Alert(
                        key=f"crawler_failed:{source}:{mode}",
                        severity="high",
                        summary=f"Краулер {source}/{mode} завершился ошибкой",
                        details=str(item.get("last_error") or "")[:300],
                        value=source,
                    )
                )

    media = observability.get("media")
    if isinstance(media, dict):
        archive_percent = float(media.get("archive_usage_percent") or 0.0)
        if archive_percent >= thresholds.archive_usage_percent:
            alerts.append(
                Alert(
                    key="archive_usage",
                    severity="warning",
                    summary=f"Архив глав заполнен на {archive_percent:.0f}%",
                    details="LRU начнёт удалять старые главы.",
                    value=round(archive_percent, 1),
                    threshold=thresholds.archive_usage_percent,
                )
            )
        cache_bytes = int(media.get("image_cache_bytes") or 0)
        if cache_bytes > thresholds.media_cache_bytes:
            alerts.append(
                Alert(
                    key="media_cache_size",
                    severity="warning",
                    summary=f"Кэш изображений {cache_bytes / 1024**3:.1f} GiB",
                    details="Проверьте MEDIA_CACHE_MAX_BYTES и LRU.",
                    value=cache_bytes,
                    threshold=thresholds.media_cache_bytes,
                )
            )

    services = observability.get("services")
    if isinstance(services, dict):
        for name, healthy in sorted(services.items()):
            if not healthy:
                alerts.append(
                    Alert(
                        key=f"service_down:{name}",
                        severity="critical",
                        summary=f"Сервис {name} недоступен",
                        details="Health check вернул не 200 или соединение не установлено.",
                        value=name,
                    )
                )

    return alerts


@dataclass
class AlertDeduplicator:
    """Persistable dedupe/cooldown state for one watchdog process."""

    cooldown_seconds: float = 3600.0
    entries: dict[str, dict[str, Any]] = field(default_factory=dict)

    def load(self, payload: str | dict[str, Any] | None) -> None:
        if payload is None:
            return
        if isinstance(payload, str):
            try:
                data = json.loads(payload) if payload.strip() else {}
            except ValueError:
                data = {}
        else:
            data = payload
        entries = data.get("entries") if isinstance(data, dict) else None
        if isinstance(entries, dict):
            self.entries = {
                str(key): value
                for key, value in entries.items()
                if isinstance(value, dict)
            }

    def dump(self) -> dict[str, Any]:
        return {"entries": self.entries}

    def select(
        self,
        alerts: list[Alert],
        *,
        now: float | None = None,
        recover_missing: bool = True,
    ) -> list[Alert]:
        """Return alerts that should be delivered, including recoveries.

        A still-active alert is suppressed until ``cooldown_seconds`` pass.  A
        severity escalation bypasses the cooldown.  An alert that disappears
        produces one ``info`` recovery message and is forgotten, so a later
        re-occurrence is delivered immediately.

        ``recover_missing=False`` keeps previous entries when a data source is
        unavailable (for example the gateway metrics endpoint is down), so a
        partial outage does not look like every alert recovered at once.
        """

        current = time.time() if now is None else now
        active_keys = {alert.key for alert in alerts}
        selected: list[Alert] = []

        for alert in alerts:
            previous = self.entries.get(alert.key)
            send = previous is None
            if previous is not None:
                last_sent = float(previous.get("last_sent_at") or 0.0)
                old_rank = SEVERITY_RANK.get(str(previous.get("severity")), 0)
                new_rank = SEVERITY_RANK.get(alert.severity, 0)
                send = (
                    new_rank > old_rank
                    or current - last_sent >= self.cooldown_seconds
                )
            if send:
                selected.append(alert)
                self.entries[alert.key] = {
                    "severity": alert.severity,
                    "summary": alert.summary,
                    "last_sent_at": current,
                    "last_seen_at": current,
                    "fingerprint": alert.fingerprint,
                    "sends": int((previous or {}).get("sends") or 0) + 1,
                }
            else:
                previous["last_seen_at"] = current
                previous["summary"] = alert.summary
                previous["fingerprint"] = alert.fingerprint

        if not recover_missing:
            return selected

        for key in list(self.entries):
            if key in active_keys:
                continue
            previous = self.entries.pop(key)
            selected.append(
                Alert(
                    key=f"recovered:{key}",
                    severity="info",
                    summary=f"Восстановлено: {previous.get('summary') or key}",
                )
            )
        return selected
