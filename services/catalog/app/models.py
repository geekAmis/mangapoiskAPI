from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from manga_common.db import Base, TimestampMixin, UUIDPrimaryKey
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

JSONType = JSON().with_variant(JSONB, "postgresql")


class Source(Base, TimestampMixin):
    __tablename__ = "sources"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="ru")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    requires_cookies: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)


class Manga(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "manga"
    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_manga_source_source_id"),
        Index("ix_manga_source_slug", "source", "slug"),
        Index("ix_manga_title", "title"),
        Index("ix_manga_group_key", "group_key"),
        Index("ix_manga_rating", "rating"),
        Index("ix_manga_last_chapter_at", "last_chapter_at"),
    )

    source: Mapped[str] = mapped_column(
        String(64), ForeignKey("sources.code", ondelete="RESTRICT"), nullable=False
    )
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    title_en: Mapped[str | None] = mapped_column(String(512), nullable=True)
    title_alt: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    rating_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    poster_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    adult: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    genres: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    group_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    chapters_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_chapter_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONType, nullable=False, default=dict
    )

    chapters: Mapped[list[Chapter]] = relationship(
        back_populates="manga", cascade="all, delete-orphan", passive_deletes=True
    )


class Chapter(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "chapters"
    __table_args__ = (
        UniqueConstraint("manga_id", "source_id", name="uq_chapters_manga_source_id"),
        Index("ix_chapters_manga_volume_number", "manga_id", "volume", "number"),
    )

    manga_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("manga.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    volume: Mapped[str | None] = mapped_column(String(64), nullable=True)
    number: Mapped[str] = mapped_column(String(64), nullable=False, default="0")
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    translator: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pages: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONType, nullable=True)
    pages_cached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_external: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_horizontal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    manga: Mapped[Manga] = relationship(back_populates="chapters")
