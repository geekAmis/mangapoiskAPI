from __future__ import annotations

import uuid
from datetime import UTC, datetime

from manga_common.db import Base, TimestampMixin, UUIDPrimaryKey
from sqlalchemy import (
    Boolean,
    DateTime,
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


class PushSubscription(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "push_subscriptions"
    __table_args__ = (
        UniqueConstraint("endpoint", name="uq_push_subscriptions_endpoint"),
        Index("ix_push_subscriptions_user_active", "user_id", "active"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    p256dh: Mapped[str] = mapped_column(String(255), nullable=False)
    auth: Mapped[str] = mapped_column(String(64), nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class PushDelivery(Base, UUIDPrimaryKey):
    """At-most-once delivery marker for one user/title/chapter on Web Push."""

    __tablename__ = "push_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "manga_id",
            "chapter_id",
            name="uq_push_deliveries_user_manga_chapter",
        ),
        Index("ix_push_deliveries_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    manga_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    chapter_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, server_default=func.now()
    )


class PushBatch(Base, UUIDPrimaryKey):
    """One logical notification per user/title, used for hourly rate limiting."""

    __tablename__ = "push_batches"
    __table_args__ = (Index("ix_push_batches_user_created", "user_id", "created_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    manga_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    chapter_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="sent")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, server_default=func.now()
    )
