from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import field_validator, model_validator
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

    # Optional protection for GET /metrics.  Services bind to 127.0.0.1 in
    # production, so it is empty by default; set it when a remote Prometheus
    # scraper reaches the service through a network.
    metrics_token: str | None = None

    # Public authentication.
    jwt_secret: str = "dev-jwt-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "mangapoisk-reborn"
    access_token_minutes: int = 30
    refresh_token_days: int = 30

    # Yandex ID OAuth 2.0 (#67).  The provider is enabled only when all three
    # values are present; empty values keep the password login untouched and
    # make /auth/yandex/start return 503.  Never expose the secret to clients.
    yandex_client_id: str | None = None
    yandex_client_secret: str | None = None
    yandex_redirect_uri: str | None = None
    yandex_authorize_url: str = "https://oauth.yandex.ru/authorize"
    yandex_token_url: str = "https://oauth.yandex.ru/token"
    yandex_profile_url: str = "https://login.yandex.ru/info"
    yandex_scope: str = "login:email login:info login:avatar"
    yandex_state_ttl_seconds: int = 600
    yandex_handoff_ttl_seconds: int = 60
    # Capacitor WebView origin used after the OAuth callback.  The mobile shell
    # serves the bundled SPA from https://localhost (androidScheme=https).
    yandex_app_return_url: str = "https://localhost"

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
    # Search Console / Yandex Webmaster verification tokens.  Empty values
    # omit the corresponding meta tag from the SPA and prerendered HTML.
    google_site_verification: str | None = None
    yandex_verification: str | None = None
    # Internal web host used by the gateway to proxy the SPA index.html for
    # humans.  Empty falls back to PUBLIC_WEB_URL/index.html.
    web_internal_url: str | None = None

    @field_validator("public_web_url", "public_api_url")
    @classmethod
    def _normalize_public_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("must be an absolute http(s) URL")
        return value

    @field_validator("yandex_client_id", "yandex_client_secret", mode="before")
    @classmethod
    def _strip_yandex_secret(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("yandex_redirect_uri", mode="before")
    @classmethod
    def _normalize_yandex_redirect_uri(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        value = value.strip().rstrip("/")
        if not value:
            return None
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("YANDEX_REDIRECT_URI must be an absolute http(s) URL")
        return value

    @field_validator("yandex_app_return_url")
    @classmethod
    def _normalize_yandex_app_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https", "capacitor"} or not parsed.netloc:
            raise ValueError("YANDEX_APP_RETURN_URL must be an absolute app URL")
        return value

    @model_validator(mode="after")
    def _require_https_public_urls(self) -> Settings:
        if not self.is_production:
            return self
        insecure = [
            field
            for field in ("public_web_url", "public_api_url")
            if urlparse(getattr(self, field)).scheme != "https"
        ]
        if self.yandex_redirect_uri and urlparse(self.yandex_redirect_uri).scheme != "https":
            insecure.append("yandex_redirect_uri")
        if insecure:
            names = ", ".join(field.upper() for field in insecure)
            raise ValueError(f"production requires HTTPS public URLs: {names}")
        return self

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

    @property
    def yandex_oauth_enabled(self) -> bool:
        """True only when every Yandex OAuth setting is present."""

        return bool(
            self.yandex_client_id
            and self.yandex_client_secret
            and self.yandex_redirect_uri
        )

    @property
    def yandex_oauth_partial(self) -> bool:
        """True when the owner configured only some of the three values."""

        configured = [
            bool(self.yandex_client_id),
            bool(self.yandex_client_secret),
            bool(self.yandex_redirect_uri),
        ]
        return any(configured) and not all(configured)

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
        if self.metrics_token and self._is_placeholder_secret(self.metrics_token):
            problems.append("METRICS_TOKEN must be changed in production")
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
