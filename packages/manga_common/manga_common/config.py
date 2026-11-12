from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Base settings shared by every service.

    Environment variables are intentionally not prefixed: containers receive a
    single flat environment and this keeps ``docker-compose.yml`` readable.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    service_name: str = "mangapoisk-service"
    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False
    log_level: str = "INFO"
    log_json: bool = True

    host: str = "0.0.0.0"
    port: int = 8000

    # Internal service-to-service authentication.  All /internal routes must
    # present this token in the X-Internal-Token header.
    internal_token: str = "dev-internal-token-change-me"

    # Public authentication.
    jwt_secret: str = "dev-jwt-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "mangapoisk-reborn"
    access_token_minutes: int = 30
    refresh_token_days: int = 30

    cors_origins: str = "http://localhost:5173,http://localhost:8080,http://localhost:3000"

    database_url: str = "sqlite+aiosqlite:///./data/service.db"
    catalog_database_url: str | None = None
    library_database_url: str | None = None
    control_database_url: str | None = None
    redis_url: str | None = None
    cache_ttl_seconds: int = 300

    media_cache_dir: str = "./data/media-cache"
    export_dir: str = "./data/exports"
    export_ttl_hours: int = 48
    max_export_pages: int = 300

    http_timeout_seconds: float = 30.0
    http_max_connections: int = 40
    http_user_agent: str = (
        "MangaPoiskReborn/1.0 (+https://github.com/geekAmis/mangapoiskAPI; "
        "polite metadata reader)"
    )

    # Public URLs of the other services.  Gateway uses these; services also use
    # them in development when running without Docker.
    parser_url: str = "http://localhost:8001"
    catalog_url: str = "http://localhost:8002"
    library_url: str = "http://localhost:8003"
    media_url: str = "http://localhost:8004"
    control_url: str = "http://localhost:8005"
    comments_url: str = "http://localhost:8109"
    notifier_url: str = "http://localhost:8006"

    # Admin panel / server manager.  Change these in production.
    admin_username: str = "admin"
    admin_password: str = "change-me-admin-password"
    admin_token_minutes: int = 60
    control_secret_key: str = "dev-control-secret-change-me"
    control_public_url: str = "http://localhost:8005"
    deploy_source_url: str = (
        "https://github.com/geekAmis/mangapoiskAPI/archive/refs/heads/main.tar.gz"
    )
    server_health_interval_seconds: int = 30

    # Scraper politeness.  Keep this conservative: the project indexes public
    # catalogue data and never tries to defeat access controls.
    scraper_requests_per_minute: int = 30
    scraper_cache_ttl_seconds: int = 600
    scraper_max_retries: int = 3
    scraper_backoff_seconds: float = 1.5

    # Optional per-source session cookies.  Never committed; documented in
    # .env.example.  Empty means anonymous/public access.
    mangapoisk_cookie: str | None = None
    mangalib_cookie: str | None = None
    remanga_cookie: str | None = None

    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    public_web_url: str = "http://localhost:8080"
    public_api_url: str = "http://localhost:8000"

    @field_validator("cors_origins")
    @classmethod
    def _strip_origins(cls, value: str) -> str:
        return ",".join(part.strip() for part in value.split(",") if part.strip())

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin for origin in self.cors_origins.split(",") if origin]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @staticmethod
    def _is_placeholder_secret(value: str) -> bool:
        """Reject the development/example values shipped with the repository."""
        return value.startswith(("dev-", "change-me"))

    def validate_production_secrets(self) -> None:
        if not self.is_production:
            return
        problems: list[str] = []
        if self._is_placeholder_secret(self.jwt_secret):
            problems.append("JWT_SECRET must be changed in production")
        if self._is_placeholder_secret(self.internal_token):
            problems.append("INTERNAL_TOKEN must be changed in production")
        if (
            self.service_name in {"gateway", "control"}
            and (
                self.admin_password == "developer-master-pro"
                or self._is_placeholder_secret(self.admin_password)
            )
        ):
            problems.append("ADMIN_PASSWORD must be changed in production")
        if self.service_name == "control" and (
            self._is_placeholder_secret(self.control_secret_key)
            or self.control_secret_key == "dev-control-secret-change-me"
        ):
            problems.append("CONTROL_SECRET_KEY must be changed in production")
        if problems:
            raise RuntimeError("; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()
