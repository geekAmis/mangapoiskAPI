from __future__ import annotations

from manga_common.config import Settings
from pydantic_settings import SettingsConfigDict


class MediaSettings(Settings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    service_name: str = "media"
    port: int = 8004

    @property
    def cache_root(self):  # type: ignore[no-untyped-def]
        from pathlib import Path

        return Path(self.media_cache_dir)

    @property
    def exports_root(self):  # type: ignore[no-untyped-def]
        from pathlib import Path

        return Path(self.export_dir)
