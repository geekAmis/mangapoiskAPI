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

    @property
    def catalog_dsn(self) -> str:
        return self.catalog_database_url or self.database_url
