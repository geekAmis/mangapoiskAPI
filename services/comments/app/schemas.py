from __future__ import annotations

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=10000)
    spoiler: bool = False
    parent_id: UUID | None = None


class CommentUpdate(BaseModel):
    body: str | None = Field(default=None, max_length=10000)
    spoiler: bool | None = None

    @model_validator(mode="after")
    def _at_least_one_change(self) -> Self:
        if self.body is None and self.spoiler is None:
            raise ValueError("Передайте body и/или spoiler")
        return self


class CommentOut(BaseModel):
    id: UUID
    manga_id: UUID
    user_id: UUID
    user_name: str
    body: str
    spoiler: bool
    parent_id: UUID | None = None
    likes_count: int = 0
    replies_count: int = 0
    liked_by_me: bool = False
    is_own: bool = False
    can_edit: bool = False
    can_delete: bool = False
    edited_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CommentThreadOut(CommentOut):
    replies: list[CommentOut] = Field(default_factory=list)


class AdminCommentOut(CommentOut):
    status: str
    deleted_at: datetime | None = None
    report_count: int = 0


class LikeOut(BaseModel):
    liked: bool
    likes_count: int


class ReportCreate(BaseModel):
    reason: str = Field(min_length=1, max_length=5000)


class ReportOut(BaseModel):
    id: UUID
    comment_id: UUID
    reporter_id: UUID
    reason: str
    status: str
    created_at: datetime


class AdminReportOut(ReportOut):
    comment: AdminCommentOut | None = None


class ReportResolveRequest(BaseModel):
    status: Literal["resolved", "dismissed"] = "resolved"


class NotificationCommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    manga_id: UUID
    user_id: UUID
    user_name: str
    body: str
    spoiler: bool
    parent_id: UUID | None = None
    status: str
    created_at: datetime


class NotificationChapterOut(BaseModel):
    manga_id: UUID
    manga_title: str
    chapter_id: UUID
    chapter_label: str
    url: str | None = None
    source: str | None = None


class NotificationOut(BaseModel):
    id: UUID
    user_id: UUID
    comment_id: UUID | None = None
    type: str
    read_at: datetime | None = None
    created_at: datetime
    comment: NotificationCommentOut | None = None
    chapter: NotificationChapterOut | None = None


class NotificationListOut(BaseModel):
    items: list[NotificationOut]
    total: int
    page: int
    limit: int
    has_next: bool = False
    unread_count: int = 0


class NotificationsReadRequest(BaseModel):
    ids: list[UUID] = Field(min_length=1, max_length=100)


class NotificationsReadOut(BaseModel):
    updated: int


class FollowCreate(BaseModel):
    manga_id: UUID
    manga_title: str = Field(min_length=1, max_length=255)
    poster_url: str | None = Field(default=None, max_length=2048)
    source: str | None = Field(default=None, max_length=64)
    variant_ids: list[UUID] = Field(default_factory=list, max_length=50)

    @field_validator("manga_title")
    @classmethod
    def _strip_title(cls, value: str) -> str:
        return value.strip()


class FollowOut(BaseModel):
    manga_id: UUID
    manga_title: str
    poster_url: str | None = None
    source: str | None = None
    created_at: datetime


class FollowStatusOut(BaseModel):
    manga_id: UUID
    following: bool


class NotificationSettingsIn(BaseModel):
    in_app_enabled: bool = True
    web_push_enabled: bool = True
    max_pushes_per_hour: int = Field(default=5, ge=1, le=60)
    quiet_hours_start: int | None = Field(default=None, ge=0, le=23)
    quiet_hours_end: int | None = Field(default=None, ge=0, le=23)

    @model_validator(mode="after")
    def _quiet_hours_pair(self) -> Self:
        if (self.quiet_hours_start is None) != (self.quiet_hours_end is None):
            raise ValueError("Укажите начало и конец тихих часов вместе")
        return self


class NotificationSettingsOut(NotificationSettingsIn):
    updated_at: datetime


class ChapterEventIn(BaseModel):
    manga_id: UUID
    chapter_id: UUID
    manga_title: str = Field(min_length=1, max_length=255)
    chapter_label: str = Field(min_length=1, max_length=128)
    chapter_url: str | None = Field(default=None, max_length=2048)
    source: str | None = Field(default=None, max_length=64)
    published_at: datetime | None = None

    @field_validator("manga_title", "chapter_label")
    @classmethod
    def _strip_event_text(cls, value: str) -> str:
        return value.strip()


class ChapterFanoutRequest(BaseModel):
    events: list[ChapterEventIn] = Field(min_length=1, max_length=50)


class PushRecipientOut(BaseModel):
    user_id: UUID
    max_pushes_per_hour: int
    quiet_hours_start: int | None = None
    quiet_hours_end: int | None = None


class ChapterFanoutOut(BaseModel):
    created: int
    followers: int
    push_recipients: int
    push: dict | None = None
