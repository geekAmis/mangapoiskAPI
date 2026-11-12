from __future__ import annotations

from manga_common.config import Settings
from pydantic import Field
from pydantic_settings import SettingsConfigDict


class ControlSettings(Settings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    service_name: str = "control"
    port: int = 8005
    control_database_url: str | None = None
    deploy_root: str = "/opt/mangapoisk-reborn"
    deploy_user: str = "mangapoisk"
    deploy_timeout_seconds: int = Field(default=3600, ge=60, le=86_400)
    deploy_health_timeout_seconds: int = Field(default=600, ge=30, le=7_200)
    deploy_health_poll_seconds: int = Field(default=2, ge=1, le=30)
    deploy_read_timeout_seconds: int = Field(default=900, ge=30, le=7_200)
    deploy_stale_job_seconds: int = Field(default=1_800, ge=60, le=86_400)
    deploy_pre_start_command: str = ""
    deploy_pre_start_timeout_seconds: int = Field(default=1_800, ge=30, le=86_400)

    @property
    def control_dsn(self) -> str:
        return self.control_database_url or self.database_url
