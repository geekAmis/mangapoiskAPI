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
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates
from sqlalchemy.types import JSON

from .normalization import genres_key, status_key

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
    status_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    content_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    rating_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    poster_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    adult: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    genres: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    genres_key: Mapped[str | None] = mapped_column(Text, nullable=True, default="")
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

    @validates("status")
    def _sync_status_key(self, _key: str, value: str | None) -> str | None:
        self.status_key = status_key(value)
        return value

    @validates("genres")
    def _sync_genres_key(self, _key: str, value: list[str] | None) -> list[str]:
        genres = list(value or [])
        self.genres_key = genres_key(genres)
        return genres


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


class MangaCover(Base, UUIDPrimaryKey, TimestampMixin):
    """A cover contributed by one source variant of a grouped title.

    Covers are retained across source variants so the detail page can expose a
    carousel; ``is_primary`` is recomputed for the whole group after every
    import.
    """

    __tablename__ = "manga_covers"
    __table_args__ = (
        UniqueConstraint("manga_id", "source", name="uq_manga_covers_manga_source"),
        Index("ix_manga_covers_group_key", "group_key"),
        Index("ix_manga_covers_manga_id", "manga_id"),
    )

    manga_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("manga.id", ondelete="CASCADE"), nullable=False
    )
    group_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    chapters_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class CrawlState(Base, UUIDPrimaryKey, TimestampMixin):
    """Persistent, resumable cursor for a source crawl mode."""

    __tablename__ = "crawl_state"
    __table_args__ = (
        UniqueConstraint("source", "mode", name="uq_crawl_state_source_mode"),
        Index("ix_crawl_state_next_run_at", "next_run_at"),
    )

    source: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(String(24), nullable=False, default="full")
    page: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    items_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_imported: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    eta_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

