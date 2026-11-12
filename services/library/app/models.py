from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from manga_common.db import Base, TimestampMixin, UUIDPrimaryKey
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

JSONType = JSON().with_variant(JSONB, "postgresql")


class User(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )


class RefreshToken(Base, UUIDPrimaryKey):
    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("ix_refresh_tokens_hash", "token_hash", unique=True),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    user: Mapped[User] = relationship(back_populates="refresh_tokens")


class Bookmark(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "bookmarks"
    __table_args__ = (UniqueConstraint("user_id", "manga_id", name="uq_bookmarks_user_manga"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    manga_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)


class ReadingProgress(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "reading_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "manga_id", name="uq_progress_user_manga"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    manga_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    chapter_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    page: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    total_pages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class UserSettings(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    data: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)


class ReadingDay(Base, UUIDPrimaryKey):
    """One row per user and UTC calendar day.

    Only the latest read timestamp of the day is kept.  A streak is computed by
    converting these timestamps into the reader's timezone at query time, which
    makes the counter portable across devices and resilient to timezone changes.
    """

    __tablename__ = "reading_days"
    __table_args__ = (
        UniqueConstraint("user_id", "utc_day", name="uq_reading_days_user_day"),
        Index("ix_reading_days_user_last_read", "user_id", "last_read_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    utc_day: Mapped[date] = mapped_column(Date, nullable=False)
    last_read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AnalyticsEvent(Base, UUIDPrimaryKey):
    """Privacy-friendly product event.

    The payload intentionally has no IP address, user agent, account id or
    free-form metadata.  ``client_id`` is a random device-local identifier used
    only for aggregate retention; it is not linkable to an account.
    """

    __tablename__ = "analytics_events"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_analytics_events_dedupe_key"),
        Index("ix_analytics_events_created_at", "created_at"),
        Index("ix_analytics_events_event_created", "event", "created_at"),
        Index("ix_analytics_events_client_created", "client_id", "created_at"),
    )

    event: Mapped[str] = mapped_column(String(32), nullable=False)
    client_id: Mapped[str] = mapped_column(String(64), nullable=False)
    surface: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    manga_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    chapter_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(96), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
