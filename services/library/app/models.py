from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from manga_common.db import Base, TimestampMixin, UUIDPrimaryKey
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
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
