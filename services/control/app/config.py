from __future__ import annotations

from manga_common.config import Settings
from pydantic_settings import SettingsConfigDict


class ControlSettings(Settings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    service_name: str = "control"
    port: int = 8005
    control_database_url: str | None = None
    deploy_root: str = "/opt/mangapoisk-reborn"
    deploy_user: str = "mangapoisk"
    deploy_timeout_seconds: int = 1800

    @property
    def control_dsn(self) -> str:
        return self.control_database_url or self.database_url
