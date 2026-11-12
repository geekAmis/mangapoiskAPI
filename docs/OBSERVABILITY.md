# Observability and alerting

Status: implemented for issues
[#54](https://github.com/geekAmis/mangapoiskAPI/issues/54) and
[#58](https://github.com/geekAmis/mangapoiskAPI/issues/58).  The production
thresholds are also listed in [`docs/OPS.md`](OPS.md) §5.

The design intentionally avoids a Prometheus/OpenTelemetry SDK in the runtime
images.  A small bounded registry in `manga_common.metrics` answers the
questions that matter for a single-node SQLite deployment:

* request count, 5xx count/ratio and p50/p95/p99 latency for 5 and 60 minutes;
* SQLite lock errors, safe-read retries, exhausted budgets and recoveries;
* per-service health, crawler backlog/ETA, archive/media usage and backup age;
* the same data in the admin **Observability** panel and in the watchdog.

Prometheus can scrape the text endpoint, or a small installation can read the
JSON endpoint directly.

## Components

| Component | Location | Purpose |
| --- | --- | --- |
| In-process registry | `packages/manga_common/manga_common/metrics.py` | Counters, gauges, rolling HTTP windows, Prometheus/JSON rendering |
| HTTP middleware + `/metrics` | `packages/manga_common/manga_common/service.py` | Counts every request except `/metrics` itself; exposes the registry |
| Gateway collector | `services/gateway/app/observability.py` | Caches service health, crawler, media, backup, disk and aggregated SQLite counters |
| Catalog/media collectors | `services/catalog/app/observability.py`, `services/media/app/observability.py` | Add DB/backlog and storage gauges to each service's `/metrics` |
| Alert rules/dedupe | `packages/manga_common/manga_common/alerts.py` | Thresholds, fingerprints, one-hour cooldown, recovery messages |
| Watchdog | `scripts/ops/mangapoisk-watchdog.py` | Runs from systemd timer or `OnFailure`, sends deduplicated Telegram alerts |
| Systemd units | `scripts/ops/mangapoisk-watchdog.{service,timer}`, `mangapoisk-alert@.service`, `mangapoisk-onfailure.conf` | Scheduling and failed-unit hooks |
| Admin panel | `apps/web/src/components/admin/ObservabilityPanel.tsx` | p95/error rate, lock counters, backup age, disk, services and active alerts |

The gateway collector refreshes every `OBSERVABILITY_REFRESH_SECONDS` (30 s by
default).  Scrapes read the cached snapshot, so a 15-second Prometheus interval
does not fan out to catalog/media every time.  Catalog and media collectors use
a 10-second cache for the same reason.

## Endpoints

| Endpoint | Auth | Format |
| --- | --- | --- |
| `GET /metrics` | loopback by default; optional `METRICS_TOKEN` | Prometheus text (`text/plain; version=0.0.4`) |
| `GET /metrics?format=json` | same | JSON registry snapshot |
| `GET /api/v1/admin/observability` (gateway) | admin JWT | Aggregated JSON used by the admin panel |
| `GET /metrics?format=json` (gateway) | same as `/metrics` | Full aggregated snapshot (health/crawler/media/backup/disk/alerts) |

When `METRICS_TOKEN` is set, send it as `X-Metrics-Token` or as a bearer token:

```bash
curl -fsS -H "X-Metrics-Token: $METRICS_TOKEN" \
  http://127.0.0.1:8100/metrics
curl -fsS -H "X-Metrics-Token: $METRICS_TOKEN" \
  'http://127.0.0.1:8100/metrics?format=json'
```

The JSON body contains counters and gauges only; it never includes
`INTERNAL_TOKEN`, `JWT_SECRET`, the admin password, the Telegram bot token or
the metrics token itself.

`/metrics` is not an admin endpoint, but the gateway JSON snapshot includes
operational data.  Keep the gateway on loopback, block `/metrics` in nginx, or
set `METRICS_TOKEN` when a remote scraper needs access.

## Metrics

### Every service (`/metrics`)

| Metric | Type | Labels | Meaning |
| --- | --- | --- | --- |
| `mangapoisk_build_info` | gauge | `service` | Always 1; identifies the process |
| `mangapoisk_uptime_seconds` | gauge | | Seconds since process start |
| `mangapoisk_http_requests_total` | counter | `method` | Lifetime requests by method |
| `mangapoisk_http_requests_all_total` | counter | | Lifetime requests across methods |
| `mangapoisk_http_5xx_total` | counter | | Lifetime 5xx responses |
| `mangapoisk_http_response_status_total` | counter | `status` | Lifetime responses by status |
| `mangapoisk_http_5xx_ratio` | gauge | `window=5m|60m` | 5xx / requests in the window |
| `mangapoisk_http_requests_window_total` | gauge | `window=5m|60m` | Requests in the window |
| `mangapoisk_http_request_duration_seconds` | gauge | `window`, `quantile=0.5|0.95|0.99` | Nearest-rank latency |
| `mangapoisk_sqlite_lock_errors_total` | counter | | `database is locked`/`busy` errors observed |
| `mangapoisk_sqlite_lock_retries_total` | counter | | Bounded safe-read retries scheduled |
| `mangapoisk_sqlite_lock_retry_exhausted_total` | counter | | Retry budget exhausted |
| `mangapoisk_sqlite_lock_recovered_total` | counter | | Read succeeded after at least one retry |
| `mangapoisk_sqlite_lock_errors_1m` / `_5m` | gauge | | Lock errors in the rolling window |
| `mangapoisk_sqlite_lock_retries_5m` | gauge | | Retries in the last 5 minutes |
| `mangapoisk_sqlite_lock_errors_per_minute_5m` | gauge | | Average lock errors per minute |

Percentiles are nearest-rank over at most 4096 samples per minute per process.
The `dropped` field in the JSON window tells you if the sample cap was reached;
request/error counts are still exact.

SQLite contention is classified by `manga_common.db.is_database_locked`
(`database is locked`, `database table is locked`, `database is busy`,
`sqlite_busy`).  Safe read retries log a WARNING and increment the counters;
write transactions are counted and logged but deliberately not retried
automatically because they need explicit idempotency.

### Gateway aggregate

| Metric | Type | Labels | Meaning |
| --- | --- | --- | --- |
| `mangapoisk_service_up` | gauge | `service` | Last `/health` result (1/0) |
| `mangapoisk_upstream_sqlite_lock_errors_total` | gauge | `service` | Lock counter reported by that service |
| `mangapoisk_upstream_sqlite_lock_errors_5m` | gauge | `service` | 5-minute lock count reported by that service |
| `mangapoisk_upstream_sqlite_lock_retries_total` | gauge | `service` | Retry counter reported by that service |
| `mangapoisk_crawler_backlog` | gauge | | Pending enrichment titles |
| `mangapoisk_crawler_backlog_source` | gauge | `source` | Pending titles per source |
| `mangapoisk_crawler_progress_ratio` | gauge | `source`, `mode` | Current page / total pages |
| `mangapoisk_crawler_eta_seconds` | gauge | `source`, `mode` | ETA reported by the crawler |
| `mangapoisk_crawler_stalled` | gauge | `source` | 1 when `running` has not progressed for 30 min |
| `mangapoisk_crawler_failed` | gauge | `source`, `mode` | 1 when the last run failed |
| `mangapoisk_media_archive_usage_ratio` | gauge | | Archive bytes / cap |
| `mangapoisk_media_archive_bytes` | gauge | | Archived chapter bytes |
| `mangapoisk_media_cache_bytes` | gauge | | Image-cache bytes |
| `mangapoisk_media_cache_usage_ratio` | gauge | | Image-cache bytes / cap |
| `mangapoisk_backup_status_configured` | gauge | | 1 when the status file was found |
| `mangapoisk_backup_status_ok` | gauge | | 1 when the last backup status is `ok` |
| `mangapoisk_backup_age_seconds` | gauge | | Age of the last successful backup; `-1` means unknown/no success yet |
| `mangapoisk_backup_last_success_timestamp_seconds` | gauge | | Unix timestamp of the last success; `0` means unknown |
| `mangapoisk_disk_used_ratio` | gauge | | Root filesystem used ratio |
| `mangapoisk_disk_free_bytes` | gauge | | Root filesystem free bytes |
| `mangapoisk_alerts_active` | gauge | `severity` | Active alerts by severity in the last snapshot |

### Catalog

| Metric | Type | Labels | Meaning |
| --- | --- | --- | --- |
| `mangapoisk_catalog_manga` / `_chapters` | gauge | | Row counts |
| `mangapoisk_catalog_enrichment_backlog` | gauge | | Pending enrichment |
| `mangapoisk_catalog_enrichment_retrying` | gauge | | Titles in retry state |
| `mangapoisk_search_backfill_remaining` | gauge | | FTS backfill rows left |
| `mangapoisk_search_backfill_progress_ratio` | gauge | | FTS backfill progress |
| `mangapoisk_search_backfill_failed` | gauge | | 1 when backfill failed |
| `mangapoisk_crawler_state` | gauge | `source`, `mode`, `status` | Crawl-state marker |

### Media

| Metric | Type | Meaning |
| --- | --- | --- |
| `mangapoisk_media_cache_bytes` / `_cap_bytes` / `_files` | gauge | Image cache usage |
| `mangapoisk_media_cache_evictions_total` | gauge | Cache evictions since start |
| `mangapoisk_media_cache_usage_ratio` | gauge | Cache bytes / cap |
| `mangapoisk_media_archive_total` / `_done` / `_failed` / `_pending` | gauge | Archive queue state |
| `mangapoisk_media_archive_bytes` / `_cap_bytes` | gauge | Archive usage |
| `mangapoisk_media_archive_evictions_total` | gauge | LRU evictions since start |
| `mangapoisk_media_archive_usage_ratio` | gauge | Archive bytes / cap |

## Alert rules and channels

Thresholds are defined in `manga_common.alerts.AlertThresholds` and can be
overridden on the gateway with the `ALERT_*` settings.  The watchdog uses the
same defaults as `docs/OPS.md` §5.

| Alert key | Condition | Severity | Channel |
| --- | --- | --- | --- |
| `service_down:<name>` | health != 200 | critical | Telegram |
| `http_5xx_rate` | > 2% over 5 min and at least 20 requests | high | Telegram |
| `http_p95_latency` | p95 > 2 s over 5 min and at least 20 requests | high | Telegram |
| `disk_usage` | >= 90% critical, >= 80% warning | critical/warning | Telegram |
| `backup_failed` | status file says `failed` | critical | Telegram |
| `backup_stale` | last success older than 26 h | critical | Telegram |
| `backup_missing` | status file absent while backups are required | critical | Telegram |
| `crawler_stalled:<source>` | `running` and no progress > 30 min | high | Telegram |
| `crawler_failed:<source>:<mode>` | last run failed | high | Telegram |
| `crawler_backlog` | > 10 000 pending titles | warning | Telegram |
| `archive_usage` | archive cap >= 80% | warning | Telegram |
| `media_cache_size` | image cache > 10 GiB | warning | Telegram |
| `sqlite_lock_rate` | > 5 lock errors/min over 5 min | high | Telegram |
| `gateway_metrics_unavailable` | watchdog cannot read the gateway snapshot | critical | Telegram |
| `service_failed:<unit>` | systemd unit entered `failed` | critical | Telegram |

Alert delivery goes through the existing notifier bot:

* `POST /internal/notify/alert` on the notifier, authenticated with
  `INTERNAL_TOKEN`;
* `ALERT_CHAT_ID` when set, otherwise `TELEGRAM_CHAT_ID`;
* the watchdog never prints or stores the bot token, internal token or metrics
  token; alert text is capped at 4096 characters.

Deduplication:

* state is kept in `WATCHDOG_STATE_FILE` (default
  `/var/lib/mangapoisk-watchdog/state.json`);
* the same alert key is suppressed for `WATCHDOG_COOLDOWN_SECONDS` (3600 s);
* a severity escalation bypasses the cooldown;
* a recovered condition produces one `info` message and is forgotten, so a
  later re-occurrence is delivered immediately;
* an undelivered alert is not remembered, so the next timer tick retries it;
* if the gateway metrics endpoint is down, existing alerts are not marked as
  recovered from an empty snapshot.

## Production installation

### 1. Environment

Add these to `/opt/mangapoisk-reborn/.env` (never commit real values):

| Variable | Required | Purpose |
| --- | --- | --- |
| `INTERNAL_TOKEN` | yes | Notifier `/internal/*` and service-to-service auth |
| `TELEGRAM_BOT_TOKEN` | yes | Existing notifier bot |
| `TELEGRAM_CHAT_ID` | yes | Fallback channel |
| `ALERT_CHAT_ID` | recommended | Separate ops channel |
| `METRICS_TOKEN` | if remote scraper | Protects `/metrics`; empty on loopback |
| `BACKUP_STATUS_FILE` | yes | `/var/lib/mangapoisk-backup/status.json` |
| `OBSERVABILITY_REFRESH_SECONDS` | optional | Gateway cache TTL (default 30) |
| `WATCHDOG_GATEWAY_METRICS_URL` | optional | Default `http://127.0.0.1:8100/metrics?format=json` |
| `WATCHDOG_STATE_FILE` | optional | Default `/var/lib/mangapoisk-watchdog/state.json` |
| `WATCHDOG_BACKUP_STATUS_FILE` | optional | Default `/var/lib/mangapoisk-backup/status.json` |
| `WATCHDOG_BACKUP_REQUIRED` | optional | `1` (default) alerts when the status file is missing |
| `WATCHDOG_DISK_PATH` | optional | Filesystem to check (default `/`) |
| `WATCHDOG_COOLDOWN_SECONDS` | optional | Dedupe window (default 3600) |

`mangapoisk-backup.service` already loads the same `EnvironmentFile`, so
`BACKUP_STATUS_FILE` is consistent between the backup writer and the gateway.

### 2. Install the watchdog units

```bash
install -m 755 scripts/ops/mangapoisk-watchdog.py /usr/local/sbin/
install -m 644 scripts/ops/mangapoisk-watchdog.service \
  scripts/ops/mangapoisk-watchdog.timer \
  scripts/ops/mangapoisk-alert@.service /etc/systemd/system/
install -d -o mangapoisk -g mangapoisk -m 750 /var/lib/mangapoisk-watchdog
systemctl daemon-reload
systemctl enable --now mangapoisk-watchdog.timer
```

The units assume the deployment layout from `docs/DEPLOYMENT.md`
(`/opt/mangapoisk-reborn/src`, venv at `/opt/mangapoisk-reborn/venv`) and the
gateway on `127.0.0.1:8100`.

Add the failed-unit hook to every long-running service.  For example:

```bash
install -d /etc/systemd/system/mangapoisk-gateway.service.d
install -m 644 scripts/ops/mangapoisk-onfailure.conf \
  /etc/systemd/system/mangapoisk-gateway.service.d/10-onfailure.conf
systemctl daemon-reload
```

Repeat the drop-in for catalog, library, media, parser, control, notifier,
comments, scheduler, replica and web.  `OnFailure=mangapoisk-alert@%n.service`
passes the failed unit name to the watchdog, which sends one deduplicated
message.

### 3. Backup status

`scripts/ops/mangapoisk-backup.sh` writes an atomically replaced, secret-free
`status.json` before and after each run:

```json
{
  "status": "ok",
  "last_attempt_at": "2026-11-13T00:15:00Z",
  "last_success_at": "2026-11-13T00:15:00Z",
  "exit_code": 0,
  "duration_seconds": 412,
  "host": "primary-85",
  "last_error": null
}
```

The gateway reads the first existing path from `BACKUP_STATUS_FILE` and
`/var/lib/mangapoisk-backup/status.json`.  The status file contains no secrets
and is mode `0644`; the directory is `0755` so the gateway user can read it.
Backup correctness itself is tracked separately in issue #66; this metric and
alert remain valid while that regression is being fixed.

### 4. Verify

```bash
# Prometheus text and JSON from the gateway
curl -fsS http://127.0.0.1:8100/metrics | head -40
curl -fsS 'http://127.0.0.1:8100/metrics?format=json' | python3 -m json.tool | head -60

# Each service exposes its own DB/backlog counters
curl -fsS 'http://127.0.0.1:8102/metrics?format=json' | python3 -m json.tool | head -40

# Alert path without sending a message
WATCHDOG_DRY_RUN=1 /opt/mangapoisk-reborn/venv/bin/python \
  /usr/local/sbin/mangapoisk-watchdog.py

# Real timer run and logs
systemctl start mangapoisk-watchdog.service
journalctl -u mangapoisk-watchdog -n 80 --no-pager
systemctl list-timers mangapoisk-watchdog.timer
```

Admin UI: open the admin panel and check the **HTTP, SQLite и бэкапы** section.
It refreshes every 15 seconds and shows the 5-minute and 60-minute windows,
per-service health, aggregated lock counters (with a per-service breakdown),
archive/cache usage, disk, backup age and active alerts.

### 5. Prometheus scrape (optional)

```yaml
scrape_configs:
  - job_name: mangapoisk-gateway
    metrics_path: /metrics
    static_configs:
      - targets: ["127.0.0.1:8100"]
    # Only when METRICS_TOKEN is set:
    # authorization:
    #   type: Bearer
    #   credentials_file: /etc/prometheus/mangapoisk-metrics-token

  - job_name: mangapoisk-catalog
    metrics_path: /metrics
    static_configs:
      - targets: ["127.0.0.1:8102"]
```

If nginx exposes the gateway publicly, block the metrics path explicitly:

```nginx
location = /metrics {
    return 404;
}
```

or allow only the monitoring host.  Never expose `/metrics` publicly without
`METRICS_TOKEN`.

## Runbook

| Symptom | Check | Action |
| --- | --- | --- |
| `service_down:*` | `systemctl status mangapoisk-<name>`, `journalctl -u ... -n 100` | Restart once; if it repeats, follow `docs/OPS.md` §7 and escalate |
| 5xx > 2% | Gateway logs, `mangapoisk_http_response_status_total`, recent deploys | Compare with deploy windows; roll back if the rate persists outside a deploy |
| p95 > 2 s | `mangapoisk_http_request_duration_seconds`, catalog logs, DB size | Check SQLite locks, slow search, disk; scale/optimize |
| `sqlite_lock_rate` | `mangapoisk_sqlite_lock_errors_per_minute_5m`, per-service breakdown, `PRAGMA journal_mode` | Confirm WAL and `busy_timeout=15000`; reduce concurrent writers; do not add a second writer |
| Disk warning/critical | `df -h`, media cache/archive usage | Clear exports/cache, verify LRU, expand volume |
| `backup_stale` / `backup_failed` | `systemctl status mangapoisk-backup.timer`, `/var/log/mangapoisk-backup.log`, `restic snapshots` | Fix restic/SSH/space; run a manual backup; see #66 |
| `backup_missing` | `ls -l /var/lib/mangapoisk-backup/status.json` | Install/repair the backup unit and permissions |
| `crawler_stalled` | `/api/v1/admin/crawl`, source cookies, parser logs | Stop the stuck run, refresh cookies, resume one source at a time |
| `crawler_failed` | `last_error`, source status | Fix auth/rate limit; do not hammer the source |
| `crawler_backlog` | `mangapoisk_catalog_enrichment_backlog` | Check scheduler/enrichment concurrency and parser quota |
| `media_cache_size` / `archive_usage` | Media stats, LRU logs | Adjust `MEDIA_CACHE_MAX_BYTES` / archive cap or expand disk |
| `gateway_metrics_unavailable` | `systemctl status mangapoisk-gateway`, `curl /metrics` | Fix gateway; watchdog keeps previous alert state instead of sending false recoveries |
| Alerts not arriving | `journalctl -u mangapoisk-watchdog`, notifier logs, `ALERT_CHAT_ID` | Verify `INTERNAL_TOKEN`, bot token, chat id; run `WATCHDOG_DRY_RUN=1` |

## Tests

The feature is covered by:

* `tests/test_metrics.py` — aggregation, nearest-rank p95, Prometheus families
  with multiple label series, JSON provider, token protection and no secret
  leakage;
* `tests/test_alerts.py` — thresholds, dedupe/cooldown, escalation, recovery,
  partial-source handling and state round-trip;
* `tests/test_db_lock_metrics.py` — lock classification, retry/recovery/
  exhausted counters;
* `tests/gateway/test_admin_observability.py` — snapshot assembly, backup status
  parsing, SQLite counter merge, admin auth;
* `tests/test_watchdog.py` — backup age/status handling and notifier delivery
  semantics;
* `tests/notifier/test_alert_endpoint.py` — dedicated alert chat, fallback chat,
  internal-token enforcement and no bot-token leakage.

Run them with the common package first on `PYTHONPATH`:

```bash
PYTHONPATH=packages/manga_common pytest -q \
  tests/test_metrics.py tests/test_alerts.py tests/test_db_lock_metrics.py \
  tests/test_watchdog.py tests/gateway/test_admin_observability.py \
  tests/notifier/test_alert_endpoint.py
```

## Known limitations

* Metrics are per process and reset on restart.  Use Prometheus (or another
  long-term store) if you need history; the admin panel and watchdog only need
  the current windows.
* The gateway snapshot is cached for 30 s; an alert can be up to one refresh
  interval late.  The watchdog timer adds up to 60 s.
* p95 is computed from in-process samples, not from nginx access logs.  The
  `dropped` counter exposes the sampling cap.
* 5xx metrics count responses produced by the application.  502s generated by
  nginx before a request reaches the gateway are not included; keep the nginx
  access log (with `$request_time`) or an external monitor for edge-level
  failures.
* The watchdog runs on the same host.  Keep an external uptime monitor for
  host/network loss, as recommended in issue #54.
* Telegram delivery depends on the notifier service and the Telegram API.  If
  the notifier itself is down, the watchdog logs the failure and retries on the
  next tick, but it cannot deliver a message about that outage through the same
  channel; use the external monitor for this case as well.
* SQLite remains single-writer.  WAL, `busy_timeout=15000`, bounded read
  retries and metrics make contention visible; this change does not attempt a
  multi-writer or PostgreSQL redesign.
* Systemd units are not installed by the application; production must install
  the timer, template unit and per-service drop-ins as described above.
