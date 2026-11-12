from __future__ import annotations

from pathlib import Path

from manga_common.config import Settings
from pydantic_settings import SettingsConfigDict


class MediaSettings(Settings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    service_name: str = "media"
    port: int = 8004

    # Persistent chapter archive.  Empty paths derive from MEDIA_CACHE_DIR so
    # they land next to the image cache (and inside the same Docker volume).
    archive_db: str | None = None
    archive_dir: str | None = None
    archive_db_threshold_bytes: int = 1024 * 1024
    # Chapter archives are an LRU disk cache: metadata and covers stay
    # unlimited in the image cache, while prepared chapters are capped at a
    # configurable 20-30 GB budget (25 GiB by default).
    archive_max_bytes: int = 25 * 1024 * 1024 * 1024

    @property
    def cache_root(self) -> Path:
        return Path(self.media_cache_dir)

    @property
    def exports_root(self) -> Path:
        return Path(self.export_dir)

    @property
    def data_root(self) -> Path:
        return self.cache_root.resolve().parent

    @property
    def archive_db_path(self) -> Path:
        if self.archive_db:
            return Path(self.archive_db)
        return self.data_root / "archives.db"

    @property
    def archive_root(self) -> Path:
        if self.archive_dir:
            return Path(self.archive_dir)
        return self.data_root / "chapter-archives"
