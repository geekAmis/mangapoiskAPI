from __future__ import annotations

from manga_common.config import Settings
from pydantic_settings import SettingsConfigDict


class CatalogSettings(Settings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    service_name: str = "catalog"
    port: int = 8002
    refresh_batch_size: int = 5
    refresh_min_interval_minutes: int = 30
    pages_stale_minutes: int = 60
    # Retention contract for the media service (enforced there): metadata and
    # covers are unlimited, decoded page archives are LRU-evicted between
    # 20 and 25 GB by default.
    chapter_archive_policy: str = "lru"
    chapter_archive_min_gb: int = 20
    chapter_archive_max_gb: int = 25
    enrichment_retry_base_seconds: int = 300
    enrichment_retry_max_seconds: int = 21600
    # Search/filter normalization is a background migration.  Keep batches
    # small enough to release the SQLite write lock regularly.
    search_backfill_enabled: bool = True
    search_backfill_batch_size: int = 500
    search_backfill_lease_seconds: int = 120
    search_backfill_yield_seconds: float = 0.01
    search_backfill_max_retries: int = 5
    # Public URL slugs are additive and backfilled in the background.  The
    # UUID remains the routing key, so a missing slug never hides a title.
    url_slug_backfill_enabled: bool = True
    url_slug_backfill_batch_size: int = 500
    url_slug_backfill_yield_seconds: float = 0.05
    # #68: keep SQLite planner stats fresh without a 21s full ANALYZE.  The
    # background loop runs PRAGMA optimize with a bounded analysis_limit.
    stats_optimize_enabled: bool = True
    stats_optimize_interval_seconds: int = 900
    slow_query_ms: int = 500
    list_latency_window: int = 512

    @property
    def catalog_dsn(self) -> str:
        return self.catalog_database_url or self.database_url
