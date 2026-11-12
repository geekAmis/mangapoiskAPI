from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from manga_common.schemas import Paginated
from manga_common.security import require_internal_token

from .auth import CommentUser, optional_comment_user, require_comment_user, require_moderator
from .schemas import (
    AdminCommentOut,
    AdminReportOut,
    CommentCreate,
    CommentOut,
    CommentThreadOut,
    CommentUpdate,
    LikeOut,
    NotificationListOut,
    NotificationsReadOut,
    NotificationsReadRequest,
    ReportCreate,
    ReportOut,
    ReportResolveRequest,
)
from .service import CommentsService

router = APIRouter(prefix="/internal", dependencies=[Depends(require_internal_token)])


def get_service(request: Request) -> CommentsService:
    return request.app.state.service


Viewer = Annotated[CommentUser, Depends(require_comment_user)]
OptionalViewer = Annotated[CommentUser | None, Depends(optional_comment_user)]
Moderator = Annotated[CommentUser, Depends(require_moderator)]
Service = Annotated[CommentsService, Depends(get_service)]


@router.get("/manga/{manga_id}/comments", response_model=Paginated[CommentThreadOut])
async def list_comments(
    manga_id: uuid.UUID,
    viewer: OptionalViewer,
    service: Service,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    sort: Literal["new", "top"] = "new",
) -> Paginated[CommentThreadOut]:
    return await service.list_comments(
        manga_id, viewer, page=page, limit=limit, sort=sort
    )


@router.post(
    "/manga/{manga_id}/comments",
    response_model=CommentOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_comment(
    manga_id: uuid.UUID,
    payload: CommentCreate,
    viewer: Viewer,
    service: Service,
) -> CommentOut:
    return await service.create_comment(manga_id, viewer, payload)


@router.get("/comments/{comment_id}/replies", response_model=Paginated[CommentOut])
async def list_replies(
    comment_id: uuid.UUID,
    viewer: OptionalViewer,
    service: Service,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
) -> Paginated[CommentOut]:
    return await service.list_replies(comment_id, viewer, page=page, limit=limit)


@router.patch("/comments/{comment_id}", response_model=CommentOut)
async def update_comment(
    comment_id: uuid.UUID,
    payload: CommentUpdate,
    viewer: Viewer,
    service: Service,
) -> CommentOut:
    return await service.update_comment(comment_id, viewer, payload)


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    comment_id: uuid.UUID,
    viewer: Viewer,
    service: Service,
) -> Response:
    await service.delete_comment(comment_id, viewer)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/comments/{comment_id}/like", response_model=LikeOut)
async def toggle_like(
    comment_id: uuid.UUID,
    viewer: Viewer,
    service: Service,
) -> LikeOut:
    return await service.toggle_like(comment_id, viewer)


@router.post(
    "/comments/{comment_id}/report",
    response_model=ReportOut,
    status_code=status.HTTP_201_CREATED,
)
async def report_comment(
    comment_id: uuid.UUID,
    payload: ReportCreate,
    viewer: Viewer,
    service: Service,
) -> ReportOut:
    return await service.report_comment(comment_id, viewer, payload.reason)


@router.get("/notifications", response_model=NotificationListOut)
async def list_notifications(
    viewer: Viewer,
    service: Service,
    unread_only: bool = False,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> NotificationListOut:
    return await service.list_notifications(
        viewer, unread_only=unread_only, page=page, limit=limit
    )


@router.post("/notifications/read", response_model=NotificationsReadOut)
async def mark_notifications_read(
    payload: NotificationsReadRequest,
    viewer: Viewer,
    service: Service,
) -> NotificationsReadOut:
    updated = await service.mark_notifications_read(viewer, payload.ids)
    return NotificationsReadOut(updated=updated)


@router.get("/admin/comments", response_model=Paginated[AdminCommentOut])
async def admin_list_comments(
    moderator: Moderator,
    service: Service,
    status_filter: Literal["visible", "hidden", "deleted"] | None = Query(
        default=None, alias="status"
    ),
    reported: bool = False,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> Paginated[AdminCommentOut]:
    return await service.admin_list_comments(
        moderator,
        status=status_filter,
        reported=reported,
        page=page,
        limit=limit,
    )


@router.post("/admin/comments/{comment_id}/hide", response_model=AdminCommentOut)
async def admin_hide_comment(
    comment_id: uuid.UUID,
    moderator: Moderator,
    service: Service,
) -> AdminCommentOut:
    return await service.admin_hide_comment(comment_id, moderator)


@router.post("/admin/comments/{comment_id}/restore", response_model=AdminCommentOut)
async def admin_restore_comment(
    comment_id: uuid.UUID,
    moderator: Moderator,
    service: Service,
) -> AdminCommentOut:
    return await service.admin_restore_comment(comment_id, moderator)


@router.get("/admin/reports", response_model=Paginated[AdminReportOut])
async def admin_list_reports(
    moderator: Moderator,
    service: Service,
    status_filter: Literal["open", "resolved", "dismissed"] | None = Query(
        default=None, alias="status"
    ),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> Paginated[AdminReportOut]:
    return await service.admin_list_reports(
        moderator, status=status_filter, page=page, limit=limit
    )


@router.post("/admin/reports/{report_id}/resolve", response_model=AdminReportOut)
async def admin_resolve_report(
    report_id: uuid.UUID,
    moderator: Moderator,
    service: Service,
    payload: ReportResolveRequest | None = None,
) -> AdminReportOut:
    resolution = payload.status if payload is not None else "resolved"
    return await service.admin_resolve_report(
        report_id, moderator, status=resolution
    )
