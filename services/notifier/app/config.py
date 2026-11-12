from __future__ import annotations

from manga_common.config import Settings
from pydantic import Field
from pydantic_settings import SettingsConfigDict


class NotifierSettings(Settings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    service_name: str = "notifier"
    port: int = 8006

    # Separate channel for operational alerts.  Falls back to TELEGRAM_CHAT_ID
    # so existing single-channel deployments keep working.
    alert_chat_id: str | None = None

    # Local SQLite by default; production may point this at PostgreSQL.
    notifier_database_url: str | None = None

    # Web Push.  Both keys are optional so Telegram-only deployments keep
    # working; /internal/push/public-key reports whether Web Push is ready.
    vapid_public_key: str | None = None
    vapid_private_key: str | None = None
    vapid_subject: str = "mailto:admin@example.com"
    web_push_enabled: bool = True
    push_ttl_seconds: int = Field(default=86400, ge=0, le=2419200)
    push_max_per_hour: int = Field(default=10, ge=1, le=60)
    push_max_subscriptions_per_user: int = Field(default=10, ge=1, le=50)
    push_quiet_hours_start: int | None = Field(default=None, ge=0, le=23)
    push_quiet_hours_end: int | None = Field(default=None, ge=0, le=23)
    # Push services are the only legitimate destinations.  A user-supplied
    # endpoint is otherwise a server-side request forgery primitive.
    push_endpoint_allowed_hosts: str = (
        "google.com,googleapis.com,updates.push.services.mozilla.com,"
        "push.services.mozilla.com,notify.windows.com,"
        "web.push.apple.com,push.apple.com"
    )
    push_allow_insecure_endpoints: bool = False

    @property
    def notifier_dsn(self) -> str:
        return self.notifier_database_url or "sqlite+aiosqlite:///./data/notifier.db"

    @property
    def allowed_push_hosts(self) -> tuple[str, ...]:
        return tuple(
            item.strip().lower()
            for item in self.push_endpoint_allowed_hosts.split(",")
            if item.strip()
        )
