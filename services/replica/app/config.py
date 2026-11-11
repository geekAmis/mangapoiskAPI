from __future__ import annotations

from pathlib import Path

from manga_common.config import Settings
from pydantic import AliasChoices, Field
from pydantic_settings import SettingsConfigDict

STORE_NAMES: tuple[str, ...] = ("catalog", "library", "control", "media")

# The live SQLite database controlled by each store.  ``media`` covers both the
# archive metadata database and the chapter ZIP files.
STORE_LIVE_FILES: dict[str, str] = {
    "catalog": "catalog.db",
    "library": "library.db",
    "control": "control.db",
    "media": "archives.db",
}


class ReplicaSettings(Settings):
    """Settings for the replica service.

    ``REPLICA_DATA_ROOT`` is accepted as an alias for ``data_root`` so the
    service can point at the same data directory as the writable services
    without setting five separate paths.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    service_name: str = "replica"
    port: int = 8108

    replica_dir: str = "data/replica"
    data_root: str = Field(
        default="/opt/mangapoisk-reborn/data",
        validation_alias=AliasChoices("REPLICA_DATA_ROOT", "data_root"),
    )

    # Every path can be overridden independently.  Empty values derive from
    # DATA_ROOT using the same names as the writable services.
    catalog_db: str | None = None
    library_db: str | None = None
    control_db: str | None = None
    media_archive_db: str | None = None
    media_archive_dir: str | None = None

    registry_url: str = "http://85.192.37.58:8088/api/v1/registry"
    sync_seconds: float = Field(
        default=10.0,
        gt=0,
        validation_alias=AliasChoices("REPLICA_SYNC_SECONDS", "sync_seconds"),
    )
    self_replica_url: str = Field(
        default="",
        validation_alias=AliasChoices("REPLICA_SELF_URL", "self_replica_url"),
    )
    sync_disabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("REPLICA_SYNC_DISABLED", "sync_disabled"),
    )

    @property
    def data_root_path(self) -> Path:
        return Path(self.data_root)

    @property
    def replica_root(self) -> Path:
        return Path(self.replica_dir)

    @property
    def snapshot_dir(self) -> Path:
        return self.replica_root / "snapshots"

    @property
    def archive_cache_dir(self) -> Path:
        return self.replica_root / "chapter-archives"

    def live_db_path(self, store: str) -> Path:
        if store not in STORE_LIVE_FILES:
            raise ValueError(f"Unknown replica store: {store}")
        explicit = {
            "catalog": self.catalog_db,
            "library": self.library_db,
            "control": self.control_db,
            "media": self.media_archive_db,
        }[store]
        if explicit:
            return Path(explicit)
        return self.data_root_path / STORE_LIVE_FILES[store]

    @property
    def media_archive_path(self) -> Path:
        if self.media_archive_dir:
            return Path(self.media_archive_dir)
        return self.data_root_path / "chapter-archives"

    @property
    def live_db_paths(self) -> dict[str, Path]:
        return {store: self.live_db_path(store) for store in STORE_NAMES}
