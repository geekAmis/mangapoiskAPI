from __future__ import annotations

from manga_common.config import Settings
from pydantic_settings import SettingsConfigDict


class GatewaySettings(Settings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    service_name: str = "gateway"
    port: int = 8000
    gateway_rate_limit_per_minute: int = 240
    gateway_search_limit_per_minute: int = 60
    gateway_suggest_limit_per_minute: int = 300
    gateway_import_limit_per_minute: int = 10
    gateway_oauth_limit_per_minute: int = 20
    live_search_max_sources: int = 4
    live_search_import_limit: int = 12

    # Observability collector.  The gateway caches upstream snapshots so a
    # Prometheus scrape (and the admin panel) do not hit catalog/media every
    # time.  BACKUP_STATUS_FILE is written by mangapoisk-backup.sh.
    observability_refresh_seconds: int = 30
    backup_status_file: str = "./data/backup-status.json"
    alert_5xx_rate: float = 0.02
    alert_p95_ms: float = 2000.0
    alert_backup_age_hours: float = 26.0
    alert_db_lock_per_minute: float = 5.0
    alert_enrichment_backlog: int = 10_000
    alert_archive_usage_percent: float = 80.0

    # Crawler prerender.  HTML is cached briefly; catalog errors/timeouts
    # always fall back to a generic card or the SPA instead of a 5xx.
    seo_prerender_cache_seconds: float = 60.0
    seo_prerender_timeout_seconds: float = 4.0
    seo_prerender_cache_max_items: int = 512
