from __future__ import annotations

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class NotificationOut(BaseModel):
    id: UUID
    user_id: UUID
    comment_id: UUID
    type: str
    read_at: datetime | None = None
    created_at: datetime
    comment: NotificationCommentOut | None = None


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
