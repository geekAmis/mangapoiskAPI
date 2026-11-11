from __future__ import annotations

from manga_common.config import Settings
from pydantic_settings import SettingsConfigDict


class LibrarySettings(Settings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    service_name: str = "library"
    port: int = 8003

    @property
    def library_dsn(self) -> str:
        return self.library_database_url or self.database_url
