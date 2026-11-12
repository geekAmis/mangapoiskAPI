"""Small dependency-free metrics registry for every MangaPoisk service.

The project deliberately does not pull Prometheus/OpenTelemetry SDKs into the
runtime images: the traffic is small and a bounded in-process registry is
enough to answer the questions from issues #54 and #58:

* request count, 5xx count and 5xx ratio for the last 5/60 minutes;
* p50/p95/p99 request latency for the same windows;
* SQLite lock/retry counters;
* per-service health, crawler backlog/ETA, media usage and backup age gauges
  (registered by the individual services).

``GET /metrics`` renders Prometheus text format and
``GET /metrics?format=json`` returns the same snapshot as JSON for the admin
panel, the watchdog and small installations without Prometheus.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

MAX_SAMPLES_PER_MINUTE = 4096
MAX_WINDOW_MINUTES = 60
DB_LOCK_EVENT_WINDOW_SECONDS = 3600


def percentile(values: Iterable[float], quantile: float) -> float:
    """Nearest-rank percentile (the same definition Prometheus summaries use).

    ``quantile`` must be in ``(0, 1]``.  An empty sample returns ``0.0`` so a
    scrape never fails just because a service has not served a request yet.
    """

    if not 0 < quantile <= 1:
        raise ValueError("quantile must be in (0, 1]")
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    rank = max(1, math.ceil(quantile * len(ordered)))
    return ordered[min(len(ordered) - 1, rank - 1)]


@dataclass
class _Bucket:
    minute: int
    requests: int = 0
    errors: int = 0
    durations: list[float] = field(default_factory=list)
    dropped: int = 0

    def record(self, status_code: int, duration_seconds: float) -> None:
        self.requests += 1
        if status_code >= 500:
            self.errors += 1
        if len(self.durations) < MAX_SAMPLES_PER_MINUTE:
            self.durations.append(max(0.0, duration_seconds))
        else:
            self.dropped += 1


@dataclass(frozen=True)
class HTTPWindowStats:
    window: str
    requests: int
    errors: int
    error_rate: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    sampled: int
    dropped: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "window": self.window,
            "requests": self.requests,
            "errors_5xx": self.errors,
            "error_rate": round(self.error_rate, 6),
            "p50_ms": round(self.p50_ms, 3),
            "p95_ms": round(self.p95_ms, 3),
            "p99_ms": round(self.p99_ms, 3),
            "sampled": self.sampled,
            "dropped": self.dropped,
        }


class RollingHTTPMetrics:
    """Bounded per-minute buckets with exact percentiles over sampled requests."""

    def __init__(self, *, clock=time.time, max_window_minutes: int = MAX_WINDOW_MINUTES) -> None:
        self._clock = clock
        self._max_window_minutes = max_window_minutes
        self._buckets: deque[_Bucket] = deque()
        self._lock = threading.Lock()
        self._total = 0
        self._errors = 0
        self._by_method: dict[str, int] = {}
        self._by_status: dict[str, int] = {}

    def _minute(self) -> int:
        return int(self._clock() // 60)

    def _bucket(self, minute: int) -> _Bucket:
        if self._buckets and self._buckets[-1].minute == minute:
            return self._buckets[-1]
        if self._buckets and self._buckets[-1].minute > minute:
            # A test clock moved backwards; keep the newest bucket only.
            self._buckets.clear()
        self._buckets.append(_Bucket(minute=minute))
        cutoff = minute - self._max_window_minutes + 1
        while self._buckets and self._buckets[0].minute < cutoff:
            self._buckets.popleft()
        return self._buckets[-1]

    def record(self, method: str, status_code: int, duration_seconds: float) -> None:
        with self._lock:
            bucket = self._bucket(self._minute())
            bucket.record(status_code, duration_seconds)
            self._total += 1
            method_key = method.upper()
            self._by_method[method_key] = self._by_method.get(method_key, 0) + 1
            status_key = str(status_code)
            self._by_status[status_key] = self._by_status.get(status_key, 0) + 1
            if status_code >= 500:
                self._errors += 1

    def window(self, minutes: int = 5) -> HTTPWindowStats:
        with self._lock:
            current = self._minute()
            cutoff = current - minutes + 1
            buckets = [bucket for bucket in self._buckets if bucket.minute >= cutoff]
            durations = [value for bucket in buckets for value in bucket.durations]
            requests = sum(bucket.requests for bucket in buckets)
            errors = sum(bucket.errors for bucket in buckets)
            dropped = sum(bucket.dropped for bucket in buckets)
        return HTTPWindowStats(
            window=f"{minutes}m",
            requests=requests,
            errors=errors,
            error_rate=(errors / requests) if requests else 0.0,
            p50_ms=percentile(durations, 0.50) * 1000,
            p95_ms=percentile(durations, 0.95) * 1000,
            p99_ms=percentile(durations, 0.99) * 1000,
            sampled=len(durations),
            dropped=dropped,
        )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            total = self._total
            errors = self._errors
            by_method = dict(self._by_method)
            by_status = dict(self._by_status)
        return {
            "total": total,
            "errors_5xx": errors,
            "error_rate": round(errors / total, 6) if total else 0.0,
            "by_method": by_method,
            "by_status": by_status,
            "windows": {
                "5m": self.window(5).as_dict(),
                "60m": self.window(60).as_dict(),
            },
        }


class MetricsRegistry:
    """Process-local counters/gauges plus the rolling HTTP window."""

    def __init__(self, *, clock=time.time, service: str = "service") -> None:
        self._clock = clock
        self._service = service
        self._started_at = clock()
        self.http = RollingHTTPMetrics(clock=clock)
        self._lock = threading.RLock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._db_lock_events: deque[float] = deque()
        self._db_lock_retry_events: deque[float] = deque()

    @property
    def service(self) -> str:
        return self._service

    def set_service(self, service: str) -> None:
        self._service = service

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._db_lock_events.clear()
            self._db_lock_retry_events.clear()
        self.http = RollingHTTPMetrics(clock=self._clock)
        self._started_at = self._clock()

    def observe_http(self, method: str, status_code: int, duration_seconds: float) -> None:
        self.http.record(method, status_code, duration_seconds)

    def inc(self, name: str, value: float = 1.0, **labels: str) -> None:
        key = (name, _label_key(labels))
        with self._lock:
            self._counters[key] = self._counters.get(key, 0.0) + value

    def set(self, name: str, value: float, **labels: str) -> None:
        self._gauges[(name, _label_key(labels))] = float(value)

    def record_db_lock_error(self) -> None:
        now = self._clock()
        with self._lock:
            self.inc("mangapoisk_sqlite_lock_errors_total")
            self._db_lock_events.append(now)
            self._trim_events(self._db_lock_events, now)

    def record_db_lock_retry(self) -> None:
        now = self._clock()
        with self._lock:
            self.inc("mangapoisk_sqlite_lock_retries_total")
            self._db_lock_retry_events.append(now)
            self._trim_events(self._db_lock_retry_events, now)

    def record_db_lock_exhausted(self) -> None:
        self.inc("mangapoisk_sqlite_lock_retry_exhausted_total")

    def record_db_lock_recovered(self) -> None:
        self.inc("mangapoisk_sqlite_lock_recovered_total")

    def _trim_events(self, events: deque[float], now: float) -> None:
        cutoff = now - DB_LOCK_EVENT_WINDOW_SECONDS
        while events and events[0] < cutoff:
            events.popleft()

    def db_lock_snapshot(self) -> dict[str, Any]:
        now = self._clock()
        with self._lock:
            for events in (self._db_lock_events, self._db_lock_retry_events):
                self._trim_events(events, now)
            errors_1m = sum(1 for stamp in self._db_lock_events if now - stamp <= 60)
            errors_5m = sum(1 for stamp in self._db_lock_events if now - stamp <= 300)
            retries_5m = sum(1 for stamp in self._db_lock_retry_events if now - stamp <= 300)
            counters = {
                name: value
                for (name, _labels), value in self._counters.items()
                if name.startswith("mangapoisk_sqlite_lock_")
            }
        return {
            "errors_total": int(counters.get("mangapoisk_sqlite_lock_errors_total", 0)),
            "retries_total": int(counters.get("mangapoisk_sqlite_lock_retries_total", 0)),
            "exhausted_total": int(
                counters.get("mangapoisk_sqlite_lock_retry_exhausted_total", 0)
            ),
            "recovered_total": int(
                counters.get("mangapoisk_sqlite_lock_recovered_total", 0)
            ),
            "errors_1m": errors_1m,
            "errors_5m": errors_5m,
            "retries_5m": retries_5m,
            "per_minute_5m": round(errors_5m / 5, 3),
        }

    def snapshot(self) -> dict[str, Any]:
        now = self._clock()
        with self._lock:
            counters = [
                {
                    "name": name,
                    "labels": dict(labels),
                    "value": value,
                }
                for (name, labels), value in sorted(self._counters.items())
            ]
            gauges = [
                {
                    "name": name,
                    "labels": dict(labels),
                    "value": value,
                }
                for (name, labels), value in sorted(self._gauges.items())
            ]
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "service": self._service,
            "uptime_seconds": round(now - self._started_at, 3),
            "http": self.http.snapshot(),
            "db": self.db_lock_snapshot(),
            "counters": counters,
            "gauges": gauges,
        }

    def render_prometheus(self) -> str:
        """Render the snapshot in Prometheus text exposition format.

        Every metric family gets exactly one ``# HELP``/``# TYPE`` pair.
        Duplicate metadata is a scrape error in Prometheus, so samples are
        grouped first and only then rendered.
        """

        snapshot = self.snapshot()
        http = snapshot["http"]
        db = snapshot["db"]

        # A metric family may contain several series (one per label set).  Keep
        # them in one family so Prometheus sees exactly one HELP/TYPE pair and
        # all per-service/per-method samples.
        families: list[dict[str, Any]] = []
        by_name: dict[str, dict[str, Any]] = {}

        def add_family(
            name: str,
            metric_type: str,
            help_text: str,
            samples: list[tuple[dict[str, str], float]],
        ) -> None:
            family = by_name.get(name)
            if family is None:
                family = {
                    "name": name,
                    "type": metric_type,
                    "help": help_text,
                    "samples": [],
                }
                by_name[name] = family
                families.append(family)
            elif family["type"] != metric_type:
                # The same name cannot be both a counter and a gauge; keep the
                # first declaration instead of emitting a scrape error.
                return
            elif help_text and not family["help"]:
                family["help"] = help_text
            family["samples"].extend(samples)

        add_family(
            "mangapoisk_build_info",
            "gauge",
            "Service build metadata.",
            [({"service": self._service}, 1.0)],
        )
        add_family(
            "mangapoisk_uptime_seconds",
            "gauge",
            "Seconds since the process started.",
            [({}, float(snapshot["uptime_seconds"]))],
        )
        add_family(
            "mangapoisk_http_requests_total",
            "counter",
            "Lifetime HTTP request count by method.",
            [
                ({"method": method}, float(value))
                for method, value in sorted(http["by_method"].items())
            ],
        )
        add_family(
            "mangapoisk_http_requests_all_total",
            "counter",
            "Lifetime HTTP request count across all methods.",
            [({}, float(http["total"]))],
        )
        add_family(
            "mangapoisk_http_5xx_total",
            "counter",
            "Lifetime 5xx response count.",
            [({}, float(http["errors_5xx"]))],
        )
        add_family(
            "mangapoisk_http_response_status_total",
            "counter",
            "Lifetime responses by status.",
            [
                ({"status": status}, float(value))
                for status, value in sorted(
                    http["by_status"].items(), key=lambda item: int(item[0])
                )
            ],
        )
        add_family(
            "mangapoisk_http_5xx_ratio",
            "gauge",
            "Rolling 5xx ratio.",
            [
                ({"window": window}, float(stats["error_rate"]))
                for window, stats in http["windows"].items()
            ],
        )
        add_family(
            "mangapoisk_http_requests_window_total",
            "gauge",
            "Rolling request count.",
            [
                ({"window": window}, float(stats["requests"]))
                for window, stats in http["windows"].items()
            ],
        )
        add_family(
            "mangapoisk_http_request_duration_seconds",
            "gauge",
            "Rolling request latency.",
            [
                ({"window": window, "quantile": quantile}, stats[key] / 1000)
                for window, stats in http["windows"].items()
                for quantile, key in (
                    ("0.5", "p50_ms"),
                    ("0.95", "p95_ms"),
                    ("0.99", "p99_ms"),
                )
            ],
        )
        add_family(
            "mangapoisk_sqlite_lock_errors_total",
            "counter",
            "SQLite lock errors seen.",
            [({}, float(db["errors_total"]))],
        )
        add_family(
            "mangapoisk_sqlite_lock_retries_total",
            "counter",
            "Safe read retries.",
            [({}, float(db["retries_total"]))],
        )
        add_family(
            "mangapoisk_sqlite_lock_retry_exhausted_total",
            "counter",
            "Retry budgets exhausted.",
            [({}, float(db["exhausted_total"]))],
        )
        add_family(
            "mangapoisk_sqlite_lock_recovered_total",
            "counter",
            "Safe reads that succeeded after a retry.",
            [({}, float(db["recovered_total"]))],
        )
        add_family(
            "mangapoisk_sqlite_lock_errors_1m",
            "gauge",
            "Lock errors in the last minute.",
            [({}, float(db["errors_1m"]))],
        )
        add_family(
            "mangapoisk_sqlite_lock_errors_5m",
            "gauge",
            "Lock errors in the last 5 minutes.",
            [({}, float(db["errors_5m"]))],
        )
        add_family(
            "mangapoisk_sqlite_lock_retries_5m",
            "gauge",
            "Safe read retries in the last 5 minutes.",
            [({}, float(db["retries_5m"]))],
        )
        add_family(
            "mangapoisk_sqlite_lock_errors_per_minute_5m",
            "gauge",
            "Average lock errors per minute over 5 minutes.",
            [({}, float(db["per_minute_5m"]))],
        )

        # Application counters are rendered generically.  SQLite lock counters
        # are already above with their rolling gauges, so skip them here to
        # avoid duplicate samples for the same series.
        for item in snapshot["counters"]:
            name = item["name"]
            if name.startswith("mangapoisk_sqlite_lock_"):
                continue
            add_family(name, "counter", "", [(item["labels"], float(item["value"]))])

        for item in snapshot["gauges"]:
            add_family(item["name"], "gauge", "", [(item["labels"], float(item["value"]))])

        lines: list[str] = []
        for family in families:
            name = family["name"]
            if family["help"]:
                lines.append(f"# HELP {name} {family['help']}")
            lines.append(f"# TYPE {name} {family['type']}")
            for labels, value in family["samples"]:
                lines.append(f"{name}{_render_labels(labels)} {value}")
        return "\n".join(lines) + "\n"


def _label_key(labels: dict[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((str(key), str(value)) for key, value in labels.items()))


def _render_labels(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    body = ",".join(
        f'{key}="{_escape_label(value)}"' for key, value in sorted(labels.items())
    )
    return "{" + body + "}"


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


# One registry per process.  DB helpers do not know about FastAPI app instances,
# so they record into this object; create_service_app exposes it on /metrics.
metrics = MetricsRegistry()


def reset_metrics() -> None:
    """Test helper: clear all counters and rolling windows."""

    metrics.reset()


def record_db_lock_error() -> None:
    metrics.record_db_lock_error()


def record_db_lock_retry() -> None:
    metrics.record_db_lock_retry()


def record_db_lock_exhausted() -> None:
    metrics.record_db_lock_exhausted()


def record_db_lock_recovered() -> None:
    metrics.record_db_lock_recovered()
