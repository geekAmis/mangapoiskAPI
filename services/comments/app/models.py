from __future__ import annotations

import uuid
from datetime import UTC, datetime

from manga_common.db import Base, TimestampMixin, UUIDPrimaryKey
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column


def _now() -> datetime:
    return datetime.now(UTC)


class Comment(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "comments"
    __table_args__ = (
        Index("ix_comments_manga_status_created", "manga_id", "status", "created_at"),
        Index("ix_comments_user_created", "user_id", "created_at"),
        CheckConstraint("status IN ('visible', 'hidden', 'deleted')", name="status"),
    )

    manga_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    user_name: Mapped[str] = mapped_column(String(64), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    spoiler: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("comments.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    likes_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    replies_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="visible", index=True, server_default="visible"
    )


class CommentLike(Base, UUIDPrimaryKey):
    __tablename__ = "comment_likes"
    __table_args__ = (
        UniqueConstraint("comment_id", "user_id", name="uq_comment_likes_comment_user"),
    )

    comment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("comments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, server_default=func.now()
    )


class CommentReport(Base, UUIDPrimaryKey):
    __tablename__ = "comment_reports"
    __table_args__ = (
        Index("ix_comment_reports_status_created", "status", "created_at"),
        CheckConstraint(
            "status IN ('open', 'resolved', 'dismissed')", name="status"
        ),
    )

    comment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("comments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reporter_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="open", index=True, server_default="open"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, server_default=func.now()
    )


class CommentNotification(Base, UUIDPrimaryKey):
    __tablename__ = "comment_notifications"
    __table_args__ = (
        Index("ix_comment_notifications_user_created", "user_id", "created_at"),
        Index("ix_comment_notifications_user_unread", "user_id", "read_at"),
        CheckConstraint("type IN ('reply', 'like', 'moderation')", name="type"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    comment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("comments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, server_default=func.now()
    )


class TitleFollow(Base, UUIDPrimaryKey):
    """A user follows one catalogue title (a group of source variants).

    ``manga_id`` is the canonical id the reader used when pressing "follow".
    ``TitleFollowAlias`` contains that id and every source-variant id so a new
    chapter discovered on any variant reaches the same subscriber.
    """

    __tablename__ = "title_follows"
    __table_args__ = (
        UniqueConstraint("user_id", "manga_id", name="uq_title_follows_user_manga"),
        Index("ix_title_follows_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    manga_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    manga_title: Mapped[str] = mapped_column(String(255), nullable=False)
    poster_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, server_default=func.now()
    )


class TitleFollowAlias(Base, UUIDPrimaryKey):
    __tablename__ = "title_follow_aliases"
    __table_args__ = (
        UniqueConstraint("follow_id", "manga_id", name="uq_title_follow_aliases_follow_manga"),
        Index("ix_title_follow_aliases_manga", "manga_id"),
    )

    follow_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("title_follows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    manga_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)


class ChapterNotification(Base, UUIDPrimaryKey):
    """In-app chapter notification.

    The unique triple is the in-app dedupe key required by issue #42:
    one chapter produces exactly one notification for one user.
    """

    __tablename__ = "chapter_notifications"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "manga_id",
            "chapter_id",
            name="uq_chapter_notifications_user_manga_chapter",
        ),
        Index("ix_chapter_notifications_user_created", "user_id", "created_at"),
        Index("ix_chapter_notifications_user_unread", "user_id", "read_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    manga_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    chapter_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    manga_title: Mapped[str] = mapped_column(String(255), nullable=False)
    chapter_label: Mapped[str] = mapped_column(String(128), nullable=False)
    chapter_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, server_default=func.now()
    )


class NotificationSettings(Base, UUIDPrimaryKey):
    __tablename__ = "notification_settings"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_notification_settings_user"),
        CheckConstraint(
            "max_pushes_per_hour BETWEEN 1 AND 60", name="push_rate"
        ),
        CheckConstraint(
            "(quiet_hours_start IS NULL AND quiet_hours_end IS NULL) OR "
            "(quiet_hours_start BETWEEN 0 AND 23 AND quiet_hours_end BETWEEN 0 AND 23)",
            name="quiet_hours",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    in_app_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    web_push_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    max_pushes_per_hour: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5, server_default="5"
    )
    quiet_hours_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quiet_hours_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_now,
        server_default=func.now(),
        onupdate=_now,
    )
