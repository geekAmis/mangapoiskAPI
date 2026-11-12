from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from .models import (
    ChapterNotification,
    Comment,
    CommentLike,
    CommentNotification,
    CommentReport,
    NotificationSettings,
    TitleFollow,
    TitleFollowAlias,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


async def get_comment(session: AsyncSession, comment_id: uuid.UUID) -> Comment | None:
    return await session.get(Comment, comment_id)


async def latest_comment_at(session: AsyncSession, user_id: uuid.UUID) -> datetime | None:
    return await session.scalar(
        select(Comment.created_at)
        .where(Comment.user_id == user_id)
        .order_by(Comment.created_at.desc())
        .limit(1)
    )


async def count_user_comments_since(
    session: AsyncSession, user_id: uuid.UUID, since: datetime
) -> int:
    value = await session.scalar(
        select(func.count())
        .select_from(Comment)
        .where(Comment.user_id == user_id, Comment.created_at >= since)
    )
    return int(value or 0)


async def duplicate_exists(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    manga_id: uuid.UUID,
    body: str,
    since: datetime,
) -> bool:
    found = await session.scalar(
        select(Comment.id)
        .where(
            Comment.user_id == user_id,
            Comment.manga_id == manga_id,
            Comment.body == body,
            Comment.created_at >= since,
        )
        .limit(1)
    )
    return found is not None


async def list_top_level(
    session: AsyncSession,
    manga_id: uuid.UUID,
    *,
    sort: str,
    offset: int,
    limit: int,
) -> list[Comment]:
    statement = select(Comment).where(
        Comment.manga_id == manga_id,
        Comment.parent_id.is_(None),
        Comment.status == "visible",
    )
    if sort == "top":
        statement = statement.order_by(
            Comment.likes_count.desc(), Comment.created_at.desc(), Comment.id.desc()
        )
    else:
        statement = statement.order_by(Comment.created_at.desc(), Comment.id.desc())
    return list(await session.scalars(statement.offset(offset).limit(limit)))


async def count_top_level(session: AsyncSession, manga_id: uuid.UUID) -> int:
    value = await session.scalar(
        select(func.count())
        .select_from(Comment)
        .where(
            Comment.manga_id == manga_id,
            Comment.parent_id.is_(None),
            Comment.status == "visible",
        )
    )
    return int(value or 0)


async def list_replies(
    session: AsyncSession,
    parent_id: uuid.UUID,
    *,
    offset: int,
    limit: int,
) -> list[Comment]:
    statement = (
        select(Comment)
        .where(Comment.parent_id == parent_id, Comment.status == "visible")
        .order_by(Comment.created_at.asc(), Comment.id.asc())
        .offset(offset)
        .limit(limit)
    )
    return list(await session.scalars(statement))


async def count_replies(session: AsyncSession, parent_id: uuid.UUID) -> int:
    value = await session.scalar(
        select(func.count())
        .select_from(Comment)
        .where(Comment.parent_id == parent_id, Comment.status == "visible")
    )
    return int(value or 0)


async def preview_replies(
    session: AsyncSession,
    parent_ids: list[uuid.UUID],
    *,
    per_parent: int,
) -> dict[uuid.UUID, list[Comment]]:
    """Return the first ``per_parent`` visible replies for every top-level id."""

    if not parent_ids or per_parent <= 0:
        return {}
    ranked = (
        select(
            Comment.id.label("comment_id"),
            func.row_number()
            .over(
                partition_by=Comment.parent_id,
                order_by=(Comment.created_at.asc(), Comment.id.asc()),
            )
            .label("position"),
        )
        .where(Comment.parent_id.in_(parent_ids), Comment.status == "visible")
        .subquery()
    )
    statement = (
        select(Comment)
        .join(ranked, Comment.id == ranked.c.comment_id)
        .where(ranked.c.position <= per_parent)
        .order_by(Comment.created_at.asc(), Comment.id.asc())
    )
    grouped: dict[uuid.UUID, list[Comment]] = defaultdict(list)
    for comment in await session.scalars(statement):
        if comment.parent_id is not None:
            grouped[comment.parent_id].append(comment)
    return dict(grouped)


async def liked_comment_ids(
    session: AsyncSession, user_id: uuid.UUID | None, comment_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    if user_id is None or not comment_ids:
        return set()
    rows = await session.scalars(
        select(CommentLike.comment_id).where(
            CommentLike.user_id == user_id,
            CommentLike.comment_id.in_(comment_ids),
        )
    )
    return set(rows)


async def get_like(
    session: AsyncSession, comment_id: uuid.UUID, user_id: uuid.UUID
) -> CommentLike | None:
    return await session.scalar(
        select(CommentLike).where(
            CommentLike.comment_id == comment_id, CommentLike.user_id == user_id
        )
    )


def add_like(session: AsyncSession, comment_id: uuid.UUID, user_id: uuid.UUID) -> None:
    session.add(CommentLike(comment_id=comment_id, user_id=user_id))


async def remove_like(session: AsyncSession, like: CommentLike) -> None:
    await session.delete(like)


async def count_likes(session: AsyncSession, comment_id: uuid.UUID) -> int:
    value = await session.scalar(
        select(func.count())
        .select_from(CommentLike)
        .where(CommentLike.comment_id == comment_id)
    )
    return int(value or 0)


async def hide_replies(session: AsyncSession, parent_id: uuid.UUID) -> None:
    await session.execute(
        update(Comment)
        .where(Comment.parent_id == parent_id, Comment.status == "visible")
        .values(status="hidden", updated_at=utcnow())
    )


def add_notification(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    comment_id: uuid.UUID,
    kind: str,
) -> None:
    session.add(CommentNotification(user_id=user_id, comment_id=comment_id, type=kind))


async def has_unread_notification(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    comment_id: uuid.UUID,
    kind: str,
) -> bool:
    found = await session.scalar(
        select(CommentNotification.id)
        .where(
            CommentNotification.user_id == user_id,
            CommentNotification.comment_id == comment_id,
            CommentNotification.type == kind,
            CommentNotification.read_at.is_(None),
        )
        .limit(1)
    )
    return found is not None


async def list_notifications(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    unread_only: bool,
    offset: int,
    limit: int,
) -> list[CommentNotification]:
    statement = select(CommentNotification).where(CommentNotification.user_id == user_id)
    if unread_only:
        statement = statement.where(CommentNotification.read_at.is_(None))
    statement = statement.order_by(
        CommentNotification.created_at.desc(), CommentNotification.id.desc()
    )
    return list(await session.scalars(statement.offset(offset).limit(limit)))


async def count_notifications(
    session: AsyncSession, user_id: uuid.UUID, *, unread_only: bool
) -> int:
    statement = select(func.count()).select_from(CommentNotification).where(
        CommentNotification.user_id == user_id
    )
    if unread_only:
        statement = statement.where(CommentNotification.read_at.is_(None))
    return int(await session.scalar(statement) or 0)


async def count_unread_notifications(session: AsyncSession, user_id: uuid.UUID) -> int:
    return await count_notifications(session, user_id, unread_only=True)


async def mark_notifications_read(
    session: AsyncSession,
    user_id: uuid.UUID,
    ids: list[uuid.UUID],
) -> int:
    result = await session.execute(
        update(CommentNotification)
        .where(
            CommentNotification.user_id == user_id,
            CommentNotification.id.in_(ids),
            CommentNotification.read_at.is_(None),
        )
        .values(read_at=utcnow())
    )
    return int(result.rowcount or 0)


def _admin_comment_conditions(
    status: str | None, reported: bool
) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if status:
        conditions.append(Comment.status == status)
    if reported:
        conditions.append(
            select(CommentReport.id)
            .where(
                CommentReport.comment_id == Comment.id,
                CommentReport.status == "open",
            )
            .exists()
        )
    return conditions


async def list_admin_comments(
    session: AsyncSession,
    *,
    status: str | None,
    reported: bool,
    offset: int,
    limit: int,
) -> list[Comment]:
    statement = select(Comment)
    for condition in _admin_comment_conditions(status, reported):
        statement = statement.where(condition)
    statement = statement.order_by(Comment.created_at.desc(), Comment.id.desc())
    return list(await session.scalars(statement.offset(offset).limit(limit)))


async def count_admin_comments(
    session: AsyncSession, *, status: str | None, reported: bool
) -> int:
    statement = select(func.count()).select_from(Comment)
    for condition in _admin_comment_conditions(status, reported):
        statement = statement.where(condition)
    return int(await session.scalar(statement) or 0)


async def open_report_counts(
    session: AsyncSession, comment_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not comment_ids:
        return {}
    rows = await session.execute(
        select(CommentReport.comment_id, func.count(CommentReport.id))
        .where(
            CommentReport.comment_id.in_(comment_ids),
            CommentReport.status == "open",
        )
        .group_by(CommentReport.comment_id)
    )
    return {comment_id: int(count) for comment_id, count in rows}


async def open_report_count(session: AsyncSession, comment_id: uuid.UUID) -> int:
    value = await session.scalar(
        select(func.count())
        .select_from(CommentReport)
        .where(CommentReport.comment_id == comment_id, CommentReport.status == "open")
    )
    return int(value or 0)


async def find_open_report(
    session: AsyncSession, comment_id: uuid.UUID, reporter_id: uuid.UUID
) -> CommentReport | None:
    return await session.scalar(
        select(CommentReport)
        .where(
            CommentReport.comment_id == comment_id,
            CommentReport.reporter_id == reporter_id,
            CommentReport.status == "open",
        )
        .limit(1)
    )


def add_report(
    session: AsyncSession,
    *,
    comment_id: uuid.UUID,
    reporter_id: uuid.UUID,
    reason: str,
) -> CommentReport:
    report = CommentReport(
        comment_id=comment_id,
        reporter_id=reporter_id,
        reason=reason,
        status="open",
    )
    session.add(report)
    return report


async def get_report(session: AsyncSession, report_id: uuid.UUID) -> CommentReport | None:
    return await session.get(CommentReport, report_id)


async def list_reports(
    session: AsyncSession,
    *,
    status: str | None,
    offset: int,
    limit: int,
) -> list[CommentReport]:
    statement = select(CommentReport)
    if status:
        statement = statement.where(CommentReport.status == status)
    statement = statement.order_by(
        CommentReport.created_at.desc(), CommentReport.id.desc()
    )
    return list(await session.scalars(statement.offset(offset).limit(limit)))


async def count_reports(session: AsyncSession, *, status: str | None) -> int:
    statement = select(func.count()).select_from(CommentReport)
    if status:
        statement = statement.where(CommentReport.status == status)
    return int(await session.scalar(statement) or 0)


async def comments_by_ids(
    session: AsyncSession, ids: list[uuid.UUID]
) -> dict[uuid.UUID, Comment]:
    if not ids:
        return {}
    rows = await session.scalars(select(Comment).where(Comment.id.in_(ids)))
    return {comment.id: comment for comment in rows}


# ---------------------------------------------------------------------------
# Title follows
# ---------------------------------------------------------------------------


async def get_follow(
    session: AsyncSession, user_id: uuid.UUID, manga_id: uuid.UUID
) -> TitleFollow | None:
    return await session.scalar(
        select(TitleFollow).where(
            TitleFollow.user_id == user_id, TitleFollow.manga_id == manga_id
        )
    )


async def add_follow(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    manga_id: uuid.UUID,
    manga_title: str,
    poster_url: str | None,
    source: str | None,
    variant_ids: list[uuid.UUID],
) -> TitleFollow:
    follow = TitleFollow(
        user_id=user_id,
        manga_id=manga_id,
        manga_title=manga_title,
        poster_url=poster_url,
        source=source,
    )
    session.add(follow)
    await session.flush()
    aliases = {manga_id, *variant_ids}
    for alias_id in aliases:
        session.add(TitleFollowAlias(follow_id=follow.id, manga_id=alias_id))
    return follow


async def add_follow_alias(
    session: AsyncSession, follow_id: uuid.UUID, manga_id: uuid.UUID
) -> None:
    exists = await session.scalar(
        select(TitleFollowAlias.id).where(
            TitleFollowAlias.follow_id == follow_id,
            TitleFollowAlias.manga_id == manga_id,
        )
    )
    if exists is None:
        session.add(TitleFollowAlias(follow_id=follow_id, manga_id=manga_id))


async def delete_follow(session: AsyncSession, follow: TitleFollow) -> None:
    await session.delete(follow)


async def list_follows(session: AsyncSession, user_id: uuid.UUID) -> list[TitleFollow]:
    return list(
        await session.scalars(
            select(TitleFollow)
            .where(TitleFollow.user_id == user_id)
            .order_by(TitleFollow.created_at.desc(), TitleFollow.id.desc())
        )
    )


async def follows_for_manga_ids(
    session: AsyncSession, manga_ids: list[uuid.UUID]
) -> list[TitleFollow]:
    if not manga_ids:
        return []
    return list(
        await session.scalars(
            select(TitleFollow)
            .join(TitleFollowAlias, TitleFollowAlias.follow_id == TitleFollow.id)
            .where(TitleFollowAlias.manga_id.in_(manga_ids))
            .distinct()
        )
    )


# ---------------------------------------------------------------------------
# Chapter notifications
# ---------------------------------------------------------------------------


async def add_chapter_notification(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    manga_id: uuid.UUID,
    chapter_id: uuid.UUID,
    manga_title: str,
    chapter_label: str,
    chapter_url: str | None,
    source: str | None,
) -> bool:
    """Insert one chapter notification, ignoring a duplicate triple.

    Returns True when a new row was created.  The unique index
    ``(user_id, manga_id, chapter_id)`` is the authoritative dedupe guard; the
    dialect-specific ``ON CONFLICT DO NOTHING`` keeps concurrent fan-outs safe.
    """

    values = {
        "id": uuid.uuid4(),
        "user_id": user_id,
        "manga_id": manga_id,
        "chapter_id": chapter_id,
        "manga_title": manga_title,
        "chapter_label": chapter_label,
        "chapter_url": chapter_url,
        "source": source,
        "read_at": None,
        "created_at": utcnow(),
    }
    bind = session.get_bind()
    dialect = bind.dialect.name if bind is not None else "sqlite"
    if dialect == "postgresql":
        statement = (
            postgresql_insert(ChapterNotification)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=["user_id", "manga_id", "chapter_id"]
            )
        )
    elif dialect == "sqlite":
        statement = (
            sqlite_insert(ChapterNotification)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=["user_id", "manga_id", "chapter_id"]
            )
        )
    else:  # pragma: no cover - only sqlite/postgres are supported deployments
        existing = await session.scalar(
            select(ChapterNotification.id).where(
                ChapterNotification.user_id == user_id,
                ChapterNotification.manga_id == manga_id,
                ChapterNotification.chapter_id == chapter_id,
            )
        )
        if existing is not None:
            return False
        session.add(ChapterNotification(**values))
        return True
    result = await session.execute(statement)
    return bool(result.rowcount)


async def list_chapter_notifications(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    unread_only: bool,
    offset: int,
    limit: int,
) -> list[ChapterNotification]:
    statement = select(ChapterNotification).where(
        ChapterNotification.user_id == user_id
    )
    if unread_only:
        statement = statement.where(ChapterNotification.read_at.is_(None))
    statement = statement.order_by(
        ChapterNotification.created_at.desc(), ChapterNotification.id.desc()
    )
    return list(await session.scalars(statement.offset(offset).limit(limit)))


async def count_chapter_notifications(
    session: AsyncSession, user_id: uuid.UUID, *, unread_only: bool
) -> int:
    statement = select(func.count()).select_from(ChapterNotification).where(
        ChapterNotification.user_id == user_id
    )
    if unread_only:
        statement = statement.where(ChapterNotification.read_at.is_(None))
    return int(await session.scalar(statement) or 0)


async def mark_chapter_notifications_read(
    session: AsyncSession, user_id: uuid.UUID, ids: list[uuid.UUID]
) -> int:
    result = await session.execute(
        update(ChapterNotification)
        .where(
            ChapterNotification.user_id == user_id,
            ChapterNotification.id.in_(ids),
            ChapterNotification.read_at.is_(None),
        )
        .values(read_at=utcnow())
    )
    return int(result.rowcount or 0)


# ---------------------------------------------------------------------------
# Notification settings
# ---------------------------------------------------------------------------


async def get_notification_settings(
    session: AsyncSession, user_id: uuid.UUID
) -> NotificationSettings | None:
    return await session.scalar(
        select(NotificationSettings).where(NotificationSettings.user_id == user_id)
    )


async def notification_settings_for_users(
    session: AsyncSession, user_ids: list[uuid.UUID]
) -> dict[uuid.UUID, NotificationSettings]:
    if not user_ids:
        return {}
    rows = await session.scalars(
        select(NotificationSettings).where(NotificationSettings.user_id.in_(user_ids))
    )
    return {row.user_id: row for row in rows}


def default_notification_settings(user_id: uuid.UUID) -> NotificationSettings:
    return NotificationSettings(user_id=user_id)


def apply_notification_settings(
    row: NotificationSettings,
    *,
    in_app_enabled: bool,
    web_push_enabled: bool,
    max_pushes_per_hour: int,
    quiet_hours_start: int | None,
    quiet_hours_end: int | None,
) -> NotificationSettings:
    row.in_app_enabled = in_app_enabled
    row.web_push_enabled = web_push_enabled
    row.max_pushes_per_hour = max_pushes_per_hour
    row.quiet_hours_start = quiet_hours_start
    row.quiet_hours_end = quiet_hours_end
    return row
