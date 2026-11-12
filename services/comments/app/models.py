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
