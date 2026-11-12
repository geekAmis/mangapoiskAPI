from __future__ import annotations

from manga_common.config import Settings
from pydantic import Field
from pydantic_settings import SettingsConfigDict


class CommentsSettings(Settings):
    """Configuration of the comments service.

    The service is intentionally independent from the catalog database: a
    ``manga_id`` is stored as an opaque UUID and there is no foreign key to the
    catalog.  The catalog may remove a title while its discussion is kept for
    moderation purposes.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    service_name: str = "comments"
    port: int = 8109

    # COMMENTS_DATABASE_URL.  ``None`` means the local SQLite default below; the
    # service never falls back to the shared DATABASE_URL on purpose.
    comments_database_url: str | None = None

    comments_edit_window_minutes: int = Field(default=15, ge=0, le=1440)
    comments_create_cooldown_seconds: int = Field(default=10, ge=0, le=86400)
    comments_create_daily_limit: int = Field(default=30, ge=1, le=10000)
    comments_duplicate_window_seconds: int = Field(default=60, ge=0, le=86400)
    comments_max_body_length: int = Field(default=2000, ge=1, le=10000)
    comments_report_reason_max_length: int = Field(default=500, ge=1, le=2000)
    comments_reply_preview_limit: int = Field(default=3, ge=0, le=10)

    @property
    def comments_dsn(self) -> str:
        return self.comments_database_url or "sqlite+aiosqlite:///./data/comments.db"
