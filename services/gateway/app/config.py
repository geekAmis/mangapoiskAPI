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
    live_search_max_sources: int = 4
    live_search_import_limit: int = 12
