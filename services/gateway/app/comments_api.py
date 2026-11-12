from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from manga_common.security import UserClaims, optional_user, require_admin, require_user
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1", tags=["comments"])


def client(request: Request):
    return request.app.state.comments


def _user_headers(user: UserClaims | None, *, include_name: bool = False) -> dict[str, str]:
    if user is None:
        return {}
    headers = {"X-User-Id": user.id, "X-User-Role": user.role}
    if include_name:
        name = (
            user.raw.get("display_name")
            or user.raw.get("username")
            or str(user.raw.get("email") or "").split("@")[0]
            or "Читатель"
        )
        headers["X-User-Name"] = quote(str(name)[:64], safe="")
    return headers


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    spoiler: bool = False
    parent_id: uuid.UUID | None = None


class CommentUpdate(BaseModel):
    body: str | None = Field(default=None, min_length=1, max_length=2000)
    spoiler: bool | None = None


class CommentReport(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class NotificationRead(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


class ModerationAction(BaseModel):
    status: Literal["resolved", "dismissed"] = "resolved"


@router.get("/manga/{manga_id}/comments")
async def list_comments(
    request: Request,
    manga_id: uuid.UUID,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    sort: Literal["new", "top"] = "new",
    user: UserClaims | None = Depends(optional_user),
) -> dict[str, Any]:
    return await client(request).list_comments(
        str(manga_id), page=page, limit=limit, sort=sort, headers=_user_headers(user)
    )


@router.post("/manga/{manga_id}/comments")
async def create_comment(
    request: Request,
    manga_id: uuid.UUID,
    payload: CommentCreate,
    user: UserClaims = Depends(require_user),
) -> dict[str, Any]:
    return await client(request).create(
        str(manga_id),
        payload.model_dump(mode="json"),
        _user_headers(user, include_name=True),
    )


@router.get("/comments/{comment_id}/replies")
async def comment_replies(
    request: Request,
    comment_id: uuid.UUID,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    user: UserClaims | None = Depends(optional_user),
) -> dict[str, Any]:
    return await client(request).replies(
        str(comment_id), page=page, limit=limit, headers=_user_headers(user)
    )


@router.patch("/comments/{comment_id}")
async def update_comment(
    request: Request,
    comment_id: uuid.UUID,
    payload: CommentUpdate,
    user: UserClaims = Depends(require_user),
) -> dict[str, Any]:
    return await client(request).update(
        str(comment_id),
        payload.model_dump(mode="json", exclude_unset=True),
        _user_headers(user, include_name=True),
    )


@router.delete("/comments/{comment_id}")
async def delete_comment(
    request: Request,
    comment_id: uuid.UUID,
    user: UserClaims = Depends(require_user),
) -> dict[str, Any]:
    await client(request).delete(str(comment_id), _user_headers(user, include_name=True))
    return {"ok": True}


@router.post("/comments/{comment_id}/like")
async def like_comment(
    request: Request,
    comment_id: uuid.UUID,
    user: UserClaims = Depends(require_user),
) -> dict[str, Any]:
    return await client(request).like(str(comment_id), _user_headers(user, include_name=True))


@router.post("/comments/{comment_id}/report")
async def report_comment(
    request: Request,
    comment_id: uuid.UUID,
    payload: CommentReport,
    user: UserClaims = Depends(require_user),
) -> dict[str, Any]:
    return await client(request).report(
        str(comment_id), payload.model_dump(mode="json"), _user_headers(user, include_name=True)
    )


@router.get("/notifications")
async def notifications(
    request: Request,
    unread_only: bool = False,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    user: UserClaims = Depends(require_user),
) -> dict[str, Any]:
    return await client(request).notifications(
        unread_only=unread_only,
        page=page,
        limit=limit,
        headers=_user_headers(user),
    )


@router.post("/notifications/read")
async def read_notifications(
    request: Request,
    payload: NotificationRead,
    user: UserClaims = Depends(require_user),
) -> dict[str, Any]:
    return await client(request).read_notifications(
        [str(item) for item in payload.ids], _user_headers(user)
    )


@router.get("/admin/comments")
async def admin_comments(
    request: Request,
    status: Literal["visible", "hidden", "deleted"] | None = None,
    reported: bool | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    user: UserClaims = Depends(require_admin),
) -> dict[str, Any]:
    return await client(request).admin_comments(
        status=status, reported=reported, page=page, limit=limit
    )


@router.post("/admin/comments/{comment_id}/{action}")
async def admin_moderate_comment(
    request: Request,
    comment_id: uuid.UUID,
    action: Literal["hide", "restore"],
    user: UserClaims = Depends(require_admin),
) -> dict[str, Any]:
    return await client(request).admin_moderate(str(comment_id), action)


@router.get("/admin/comment-reports")
async def admin_reports(
    request: Request,
    status: Literal["open", "resolved", "dismissed"] | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    user: UserClaims = Depends(require_admin),
) -> dict[str, Any]:
    return await client(request).admin_reports(status=status, page=page, limit=limit)


@router.post("/admin/comment-reports/{report_id}/resolve")
async def admin_resolve_report(
    request: Request,
    report_id: uuid.UUID,
    payload: ModerationAction,
    user: UserClaims = Depends(require_admin),
) -> dict[str, Any]:
    return await client(request).admin_resolve_report(str(report_id), payload.status)
