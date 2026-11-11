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

    @property
    def catalog_dsn(self) -> str:
        return self.catalog_database_url or self.database_url
