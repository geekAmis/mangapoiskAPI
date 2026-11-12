from __future__ import annotations

import math
import re
import uuid
from datetime import datetime, timedelta

from manga_common.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    ValidationError,
)
from manga_common.pagination import PageParams
from manga_common.schemas import Paginated
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from . import repository as repo
from .auth import CommentUser
from .config import CommentsSettings
from .models import Comment, CommentNotification, CommentReport
from .schemas import (
    AdminCommentOut,
    AdminReportOut,
    CommentCreate,
    CommentOut,
    CommentThreadOut,
    CommentUpdate,
    LikeOut,
    NotificationCommentOut,
    NotificationListOut,
    NotificationOut,
    ReportOut,
)

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _normalize_text(raw: str) -> str:
    """Normalise user text without interpreting HTML.

    Comments are plain text.  We only unify line endings, drop non-printable
    control characters and trim redundant whitespace/newlines.  Angle brackets
    are preserved so the API round-trips exactly what the author typed; the web
    client must render the value as text (React does this by default), never as
    HTML.
    """

    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_CHARS.sub("", text)
    text = "\n".join(line.rstrip() for line in text.split("\n")).strip()
    return re.sub(r"\n{4,}", "\n\n\n", text)


def _as_utc(value: datetime) -> datetime:
    converted = repo.as_utc(value)
    return converted if converted is not None else value


class CommentsService:
    def __init__(
        self,
        settings: CommentsSettings,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory

    # ------------------------------------------------------------------ text
    def normalize_body(self, raw: str) -> str:
        body = _normalize_text(raw)
        if not body:
            raise ValidationError("Комментарий не может быть пустым", code="empty_body")
        if len(body) > self.settings.comments_max_body_length:
            raise ValidationError(
                "Комментарий слишком длинный: максимум "
                f"{self.settings.comments_max_body_length} символов",
                code="body_too_long",
            )
        return body

    def normalize_reason(self, raw: str) -> str:
        reason = _normalize_text(raw)
        if not reason:
            raise ValidationError("Причина жалобы не может быть пустой", code="empty_reason")
        if len(reason) > self.settings.comments_report_reason_max_length:
            raise ValidationError(
                "Причина жалобы слишком длинная: максимум "
                f"{self.settings.comments_report_reason_max_length} символов",
                code="reason_too_long",
            )
        return reason

    def _within_edit_window(self, comment: Comment, now: datetime) -> bool:
        created = repo.as_utc(comment.created_at)
        if created is None:
            return False
        return now - created <= timedelta(minutes=self.settings.comments_edit_window_minutes)

    # ------------------------------------------------------------- responses
    def _comment_out(
        self,
        comment: Comment,
        viewer: CommentUser | None,
        *,
        liked: bool,
        now: datetime,
    ) -> CommentOut:
        is_own = viewer is not None and viewer.id == comment.user_id
        is_moderator = viewer is not None and viewer.is_moderator
        visible = comment.status == "visible"
        return CommentOut(
            id=comment.id,
            manga_id=comment.manga_id,
            user_id=comment.user_id,
            user_name=comment.user_name,
            body=comment.body,
            spoiler=comment.spoiler,
            parent_id=comment.parent_id,
            likes_count=comment.likes_count,
            replies_count=comment.replies_count,
            liked_by_me=liked,
            is_own=is_own,
            can_edit=is_own and visible and self._within_edit_window(comment, now),
            can_delete=(is_own or is_moderator) and visible,
            edited_at=repo.as_utc(comment.edited_at),
            created_at=_as_utc(comment.created_at),
            updated_at=_as_utc(comment.updated_at),
        )

    def _thread_out(
        self,
        comment: Comment,
        replies: list[Comment],
        viewer: CommentUser | None,
        *,
        liked_ids: set[uuid.UUID],
        now: datetime,
    ) -> CommentThreadOut:
        base = self._comment_out(
            comment, viewer, liked=comment.id in liked_ids, now=now
        )
        return CommentThreadOut(
            **base.model_dump(),
            replies=[
                self._comment_out(
                    reply, viewer, liked=reply.id in liked_ids, now=now
                )
                for reply in replies
            ],
        )

    def _admin_out(
        self,
        comment: Comment,
        viewer: CommentUser,
        *,
        liked: bool,
        now: datetime,
        report_count: int,
    ) -> AdminCommentOut:
        base = self._comment_out(comment, viewer, liked=liked, now=now)
        return AdminCommentOut(
            **base.model_dump(),
            status=comment.status,
            deleted_at=repo.as_utc(comment.deleted_at),
            report_count=report_count,
        )

    def _notification_out(
        self, notification: CommentNotification, comment: Comment | None
    ) -> NotificationOut:
        return NotificationOut(
            id=notification.id,
            user_id=notification.user_id,
            comment_id=notification.comment_id,
            type=notification.type,
            read_at=repo.as_utc(notification.read_at),
            created_at=_as_utc(notification.created_at),
            comment=(
                NotificationCommentOut.model_validate(comment) if comment is not None else None
            ),
        )

    def _report_out(self, report: CommentReport) -> ReportOut:
        return ReportOut(
            id=report.id,
            comment_id=report.comment_id,
            reporter_id=report.reporter_id,
            reason=report.reason,
            status=report.status,
            created_at=_as_utc(report.created_at),
        )

    def _admin_report_out(
        self,
        report: CommentReport,
        comment: Comment | None,
        admin: CommentUser,
        *,
        liked_ids: set[uuid.UUID],
        now: datetime,
        report_count: int,
    ) -> AdminReportOut:
        base = self._report_out(report)
        return AdminReportOut(
            **base.model_dump(),
            comment=(
                self._admin_out(
                    comment,
                    admin,
                    liked=comment.id in liked_ids,
                    now=now,
                    report_count=report_count,
                )
                if comment is not None
                else None
            ),
        )

    # --------------------------------------------------------------- reading
    async def list_comments(
        self,
        manga_id: uuid.UUID,
        viewer: CommentUser | None,
        *,
        page: int,
        limit: int,
        sort: str,
    ) -> Paginated[CommentThreadOut]:
        params = PageParams(page=page, limit=limit)
        now = repo.utcnow()
        async with self.session_factory() as session:
            total = await repo.count_top_level(session, manga_id)
            roots = await repo.list_top_level(
                session,
                manga_id,
                sort=sort,
                offset=params.offset,
                limit=params.limit,
            )
            reply_map = await repo.preview_replies(
                session,
                [root.id for root in roots],
                per_parent=self.settings.comments_reply_preview_limit,
            )
            preview = [reply for replies in reply_map.values() for reply in replies]
            liked_ids = await repo.liked_comment_ids(
                session,
                viewer.id if viewer is not None else None,
                [root.id for root in roots] + [reply.id for reply in preview],
            )
            items = [
                self._thread_out(
                    root,
                    reply_map.get(root.id, []),
                    viewer,
                    liked_ids=liked_ids,
                    now=now,
                )
                for root in roots
            ]
            return Paginated[CommentThreadOut](
                items=items,
                total=total,
                page=params.page,
                limit=params.limit,
                has_next=params.has_next(total),
            )

    async def list_replies(
        self,
        comment_id: uuid.UUID,
        viewer: CommentUser | None,
        *,
        page: int,
        limit: int,
    ) -> Paginated[CommentOut]:
        params = PageParams(page=page, limit=limit)
        now = repo.utcnow()
        async with self.session_factory() as session:
            parent = await repo.get_comment(session, comment_id)
            if (
                parent is None
                or parent.status != "visible"
                or parent.parent_id is not None
            ):
                raise NotFoundError("Комментарий не найден", code="comment_not_found")
            total = await repo.count_replies(session, comment_id)
            replies = await repo.list_replies(
                session, comment_id, offset=params.offset, limit=params.limit
            )
            liked_ids = await repo.liked_comment_ids(
                session,
                viewer.id if viewer is not None else None,
                [reply.id for reply in replies],
            )
            return Paginated[CommentOut](
                items=[
                    self._comment_out(
                        reply, viewer, liked=reply.id in liked_ids, now=now
                    )
                    for reply in replies
                ],
                total=total,
                page=params.page,
                limit=params.limit,
                has_next=params.has_next(total),
            )

    # -------------------------------------------------------------- creation
    async def _enforce_create_limits(
        self,
        session: AsyncSession,
        viewer: CommentUser,
        manga_id: uuid.UUID,
        body: str,
        now: datetime,
    ) -> None:
        cooldown = self.settings.comments_create_cooldown_seconds
        if cooldown > 0:
            latest = await repo.latest_comment_at(session, viewer.id)
            if latest is not None:
                elapsed = (now - _as_utc(latest)).total_seconds()
                if elapsed < cooldown:
                    retry_after = max(1, math.ceil(cooldown - elapsed))
                    raise RateLimitError(
                        "Слишком часто. Подождите перед отправкой следующего комментария.",
                        code="comment_cooldown",
                        details={"retry_after_seconds": retry_after},
                        headers={"Retry-After": str(retry_after)},
                    )

        since = now - timedelta(days=1)
        recent = await repo.count_user_comments_since(session, viewer.id, since)
        if recent >= self.settings.comments_create_daily_limit:
            raise RateLimitError(
                "Достигнут суточный лимит комментариев. Попробуйте позже.",
                code="comment_daily_limit",
                details={"limit": self.settings.comments_create_daily_limit},
                headers={"Retry-After": "3600"},
            )

        duplicate_window = self.settings.comments_duplicate_window_seconds
        if duplicate_window > 0 and await repo.duplicate_exists(
            session,
            user_id=viewer.id,
            manga_id=manga_id,
            body=body,
            since=now - timedelta(seconds=duplicate_window),
        ):
            raise ConflictError(
                "Такой комментарий уже был отправлен недавно.",
                code="duplicate_comment",
            )

    async def create_comment(
        self,
        manga_id: uuid.UUID,
        viewer: CommentUser,
        payload: CommentCreate,
    ) -> CommentOut:
        body = self.normalize_body(payload.body)
        now = repo.utcnow()
        async with self.session_factory() as session:
            parent: Comment | None = None
            if payload.parent_id is not None:
                parent = await repo.get_comment(session, payload.parent_id)
                if parent is None or parent.status != "visible":
                    raise NotFoundError(
                        "Родительский комментарий не найден", code="parent_not_found"
                    )
                if parent.manga_id != manga_id:
                    raise ValidationError(
                        "Родительский комментарий относится к другому тайтлу",
                        code="parent_manga_mismatch",
                    )
                if parent.parent_id is not None:
                    raise ValidationError(
                        "Ответы поддерживаются только на комментарии верхнего уровня",
                        code="reply_depth_exceeded",
                    )

            await self._enforce_create_limits(session, viewer, manga_id, body, now)

            comment = Comment(
                manga_id=manga_id,
                user_id=viewer.id,
                user_name=viewer.name,
                body=body,
                spoiler=payload.spoiler,
                parent_id=parent.id if parent is not None else None,
                status="visible",
            )
            session.add(comment)
            await session.flush()

            if parent is not None:
                parent.replies_count = await repo.count_replies(session, parent.id)
                if parent.user_id != viewer.id:
                    repo.add_notification(
                        session,
                        user_id=parent.user_id,
                        comment_id=comment.id,
                        kind="reply",
                    )

            await session.commit()
            return self._comment_out(comment, viewer, liked=False, now=now)

    # ------------------------------------------------------------------ edit
    async def update_comment(
        self,
        comment_id: uuid.UUID,
        viewer: CommentUser,
        payload: CommentUpdate,
    ) -> CommentOut:
        now = repo.utcnow()
        body = self.normalize_body(payload.body) if payload.body is not None else None
        async with self.session_factory() as session:
            comment = await repo.get_comment(session, comment_id)
            if comment is None or comment.status != "visible":
                raise NotFoundError("Комментарий не найден", code="comment_not_found")
            if comment.user_id != viewer.id:
                raise ForbiddenError(
                    "Редактировать комментарий может только автор", code="not_author"
                )
            if not self._within_edit_window(comment, now):
                raise ForbiddenError(
                    "Время редактирования комментария истекло", code="edit_window_expired"
                )

            changed = False
            if body is not None and body != comment.body:
                comment.body = body
                changed = True
            if payload.spoiler is not None and payload.spoiler != comment.spoiler:
                comment.spoiler = payload.spoiler
                changed = True
            if changed:
                comment.edited_at = now

            liked_ids = await repo.liked_comment_ids(session, viewer.id, [comment.id])
            await session.commit()
            return self._comment_out(
                comment, viewer, liked=comment.id in liked_ids, now=now
            )

    async def delete_comment(
        self, comment_id: uuid.UUID, viewer: CommentUser
    ) -> None:
        now = repo.utcnow()
        async with self.session_factory() as session:
            comment = await repo.get_comment(session, comment_id)
            if comment is None or comment.status != "visible":
                raise NotFoundError("Комментарий не найден", code="comment_not_found")
            if comment.user_id != viewer.id and not viewer.is_moderator:
                raise ForbiddenError(
                    "Удалить комментарий может только автор или модератор",
                    code="not_allowed",
                )

            comment.status = "deleted"
            comment.deleted_at = now
            if comment.parent_id is None:
                await repo.hide_replies(session, comment.id)
                comment.replies_count = 0
            else:
                parent = await repo.get_comment(session, comment.parent_id)
                if parent is not None:
                    await session.flush()
                    parent.replies_count = await repo.count_replies(session, parent.id)
            await session.commit()

    # ----------------------------------------------------------------- likes
    async def toggle_like(self, comment_id: uuid.UUID, viewer: CommentUser) -> LikeOut:
        async with self.session_factory() as session:
            comment = await repo.get_comment(session, comment_id)
            if comment is None or comment.status != "visible":
                raise NotFoundError("Комментарий не найден", code="comment_not_found")

            like = await repo.get_like(session, comment_id, viewer.id)
            if like is not None:
                await repo.remove_like(session, like)
                await session.flush()
                liked = False
            else:
                repo.add_like(session, comment_id, viewer.id)
                await session.flush()
                liked = True
                if comment.user_id != viewer.id and not await repo.has_unread_notification(
                    session,
                    user_id=comment.user_id,
                    comment_id=comment.id,
                    kind="like",
                ):
                    repo.add_notification(
                        session,
                        user_id=comment.user_id,
                        comment_id=comment.id,
                        kind="like",
                    )

            comment.likes_count = await repo.count_likes(session, comment.id)
            await session.commit()
            return LikeOut(liked=liked, likes_count=comment.likes_count)

    # --------------------------------------------------------------- reports
    async def report_comment(
        self, comment_id: uuid.UUID, viewer: CommentUser, reason: str
    ) -> ReportOut:
        normalized = self.normalize_reason(reason)
        async with self.session_factory() as session:
            comment = await repo.get_comment(session, comment_id)
            if comment is None or comment.status != "visible":
                raise NotFoundError("Комментарий не найден", code="comment_not_found")
            if await repo.find_open_report(session, comment_id, viewer.id) is not None:
                raise ConflictError(
                    "Вы уже отправили жалобу на этот комментарий",
                    code="report_exists",
                )
            report = repo.add_report(
                session,
                comment_id=comment_id,
                reporter_id=viewer.id,
                reason=normalized,
            )
            await session.flush()
            await session.commit()
            return self._report_out(report)

    # --------------------------------------------------------- notifications
    async def list_notifications(
        self,
        viewer: CommentUser,
        *,
        unread_only: bool,
        page: int,
        limit: int,
    ) -> NotificationListOut:
        params = PageParams(page=page, limit=limit)
        async with self.session_factory() as session:
            total = await repo.count_notifications(
                session, viewer.id, unread_only=unread_only
            )
            unread_count = await repo.count_unread_notifications(session, viewer.id)
            notifications = await repo.list_notifications(
                session,
                viewer.id,
                unread_only=unread_only,
                offset=params.offset,
                limit=params.limit,
            )
            comments = await repo.comments_by_ids(
                session, [item.comment_id for item in notifications]
            )
            return NotificationListOut(
                items=[
                    self._notification_out(item, comments.get(item.comment_id))
                    for item in notifications
                ],
                total=total,
                page=params.page,
                limit=params.limit,
                has_next=params.has_next(total),
                unread_count=unread_count,
            )

    async def mark_notifications_read(
        self, viewer: CommentUser, ids: list[uuid.UUID]
    ) -> int:
        async with self.session_factory() as session:
            updated = await repo.mark_notifications_read(session, viewer.id, ids)
            await session.commit()
            return updated

    # ------------------------------------------------------------ moderation
    async def admin_list_comments(
        self,
        admin: CommentUser,
        *,
        status: str | None,
        reported: bool,
        page: int,
        limit: int,
    ) -> Paginated[AdminCommentOut]:
        params = PageParams(page=page, limit=limit)
        now = repo.utcnow()
        async with self.session_factory() as session:
            total = await repo.count_admin_comments(
                session, status=status, reported=reported
            )
            comments = await repo.list_admin_comments(
                session,
                status=status,
                reported=reported,
                offset=params.offset,
                limit=params.limit,
            )
            ids = [comment.id for comment in comments]
            report_counts = await repo.open_report_counts(session, ids)
            liked_ids = await repo.liked_comment_ids(session, admin.id, ids)
            return Paginated[AdminCommentOut](
                items=[
                    self._admin_out(
                        comment,
                        admin,
                        liked=comment.id in liked_ids,
                        now=now,
                        report_count=report_counts.get(comment.id, 0),
                    )
                    for comment in comments
                ],
                total=total,
                page=params.page,
                limit=params.limit,
                has_next=params.has_next(total),
            )

    async def admin_hide_comment(
        self, comment_id: uuid.UUID, admin: CommentUser
    ) -> AdminCommentOut:
        now = repo.utcnow()
        async with self.session_factory() as session:
            comment = await repo.get_comment(session, comment_id)
            if comment is None:
                raise NotFoundError("Комментарий не найден", code="comment_not_found")
            if comment.status == "deleted":
                raise ConflictError(
                    "Комментарий удалён. Сначала восстановите его.",
                    code="comment_deleted",
                )
            if comment.status != "hidden":
                comment.status = "hidden"
                if comment.parent_id is not None:
                    parent = await repo.get_comment(session, comment.parent_id)
                    if parent is not None:
                        await session.flush()
                        parent.replies_count = await repo.count_replies(
                            session, parent.id
                        )
                if comment.user_id != admin.id and not await repo.has_unread_notification(
                    session,
                    user_id=comment.user_id,
                    comment_id=comment.id,
                    kind="moderation",
                ):
                    repo.add_notification(
                        session,
                        user_id=comment.user_id,
                        comment_id=comment.id,
                        kind="moderation",
                    )
                await session.commit()

            liked_ids = await repo.liked_comment_ids(session, admin.id, [comment.id])
            report_count = await repo.open_report_count(session, comment.id)
            return self._admin_out(
                comment,
                admin,
                liked=comment.id in liked_ids,
                now=now,
                report_count=report_count,
            )

    async def admin_restore_comment(
        self, comment_id: uuid.UUID, admin: CommentUser
    ) -> AdminCommentOut:
        now = repo.utcnow()
        async with self.session_factory() as session:
            comment = await repo.get_comment(session, comment_id)
            if comment is None:
                raise NotFoundError("Комментарий не найден", code="comment_not_found")
            if comment.status != "visible":
                if comment.parent_id is not None:
                    parent = await repo.get_comment(session, comment.parent_id)
                    if parent is None or parent.status != "visible":
                        raise ConflictError(
                            "Сначала восстановите родительский комментарий",
                            code="parent_unavailable",
                        )
                comment.status = "visible"
                comment.deleted_at = None
                if comment.parent_id is not None:
                    parent = await repo.get_comment(session, comment.parent_id)
                    if parent is not None:
                        await session.flush()
                        parent.replies_count = await repo.count_replies(
                            session, parent.id
                        )
                await session.commit()

            liked_ids = await repo.liked_comment_ids(session, admin.id, [comment.id])
            report_count = await repo.open_report_count(session, comment.id)
            return self._admin_out(
                comment,
                admin,
                liked=comment.id in liked_ids,
                now=now,
                report_count=report_count,
            )

    async def admin_list_reports(
        self,
        admin: CommentUser,
        *,
        status: str | None,
        page: int,
        limit: int,
    ) -> Paginated[AdminReportOut]:
        params = PageParams(page=page, limit=limit)
        now = repo.utcnow()
        async with self.session_factory() as session:
            total = await repo.count_reports(session, status=status)
            reports = await repo.list_reports(
                session, status=status, offset=params.offset, limit=params.limit
            )
            comment_ids = [report.comment_id for report in reports]
            comments = await repo.comments_by_ids(session, comment_ids)
            report_counts = await repo.open_report_counts(session, comment_ids)
            liked_ids = await repo.liked_comment_ids(session, admin.id, comment_ids)
            return Paginated[AdminReportOut](
                items=[
                    self._admin_report_out(
                        report,
                        comments.get(report.comment_id),
                        admin,
                        liked_ids=liked_ids,
                        now=now,
                        report_count=report_counts.get(report.comment_id, 0),
                    )
                    for report in reports
                ],
                total=total,
                page=params.page,
                limit=params.limit,
                has_next=params.has_next(total),
            )

    async def admin_resolve_report(
        self,
        report_id: uuid.UUID,
        admin: CommentUser,
        *,
        status: str,
    ) -> AdminReportOut:
        now = repo.utcnow()
        async with self.session_factory() as session:
            report = await repo.get_report(session, report_id)
            if report is None:
                raise NotFoundError("Жалоба не найдена", code="report_not_found")
            if report.status == "open":
                report.status = status
                await session.commit()

            comment = await repo.get_comment(session, report.comment_id)
            comment_ids = [report.comment_id]
            report_counts = await repo.open_report_counts(session, comment_ids)
            liked_ids = await repo.liked_comment_ids(session, admin.id, comment_ids)
            return self._admin_report_out(
                report,
                comment,
                admin,
                liked_ids=liked_ids,
                now=now,
                report_count=report_counts.get(report.comment_id, 0),
            )
