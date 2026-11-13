from __future__ import annotations

import secrets
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    AnalyticsEvent,
    Bookmark,
    OAuthHandoffCode,
    OAuthState,
    ReadingDay,
    ReadingProgress,
    RefreshToken,
    TrafficVisit,
    User,
    UserSettings,
)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def utc_day(value: datetime) -> date:
    moment = as_utc(value) or datetime.now(UTC)
    return moment.astimezone(UTC).date()


async def record_reading_day(
    session: AsyncSession, *, user_id: uuid.UUID, read_at: datetime
) -> ReadingDay:
    """Upsert the user's latest read timestamp for one UTC day."""

    moment = as_utc(read_at) or datetime.now(UTC)
    day = moment.astimezone(UTC).date()
    existing = await session.scalar(
        select(ReadingDay).where(ReadingDay.user_id == user_id, ReadingDay.utc_day == day)
    )
    if existing is None:
        existing = ReadingDay(user_id=user_id, utc_day=day, last_read_at=moment)
        session.add(existing)
    elif (as_utc(existing.last_read_at) or moment) < moment:
        existing.last_read_at = moment
    await session.flush()
    return existing


async def list_reading_days(
    session: AsyncSession, user_id: uuid.UUID, limit: int = 400
) -> list[ReadingDay]:
    result = await session.scalars(
        select(ReadingDay)
        .where(ReadingDay.user_id == user_id)
        .order_by(ReadingDay.last_read_at.desc())
        .limit(limit)
    )
    return list(result.all())


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(select(User).where(User.email == email.lower().strip()))


async def get_user_by_yandex_id(session: AsyncSession, yandex_id: str) -> User | None:
    return await session.scalar(select(User).where(User.yandex_id == yandex_id))


async def create_user(
    session: AsyncSession,
    *,
    email: str,
    password_hash: str,
    display_name: str,
    yandex_id: str | None = None,
    auth_provider: str = "password",
) -> User:
    user = User(
        email=email.lower().strip(),
        password_hash=password_hash,
        display_name=display_name.strip(),
        yandex_id=yandex_id,
        auth_provider=auth_provider,
    )
    session.add(user)
    await session.flush()
    session.add(UserSettings(user_id=user.id, data={}))
    await session.flush()
    return user


async def create_oauth_state(
    session: AsyncSession,
    *,
    provider: str,
    state_hash: str,
    browser_hash: str | None,
    return_url: str,
    next_path: str,
    expires_at: datetime,
) -> OAuthState:
    state = OAuthState(
        provider=provider,
        state_hash=state_hash,
        browser_hash=browser_hash,
        return_url=return_url,
        next_path=next_path,
        expires_at=expires_at,
    )
    session.add(state)
    await session.flush()
    return state


async def consume_oauth_state(
    session: AsyncSession,
    *,
    provider: str,
    state_hash: str,
    browser_hash: str | None,
) -> OAuthState | None:
    """Atomically consume a state row, or return ``None`` if it is unusable."""

    state = await session.scalar(
        select(OAuthState).where(
            OAuthState.provider == provider, OAuthState.state_hash == state_hash
        )
    )
    if state is None:
        return None
    now = datetime.now(UTC)
    expires_at = as_utc(state.expires_at)
    if state.used_at is not None or expires_at is None or expires_at <= now:
        return None
    if state.browser_hash and (
        not browser_hash or not secrets.compare_digest(state.browser_hash, browser_hash)
    ):
        return None
    result = await session.execute(
        update(OAuthState)
        .where(OAuthState.id == state.id, OAuthState.used_at.is_(None))
        .values(used_at=now)
    )
    if not result.rowcount:
        return None
    await session.flush()
    return state


async def purge_expired_oauth_artifacts(session: AsyncSession) -> None:
    """Best-effort cleanup; rows are tiny and this never blocks a login."""

    cutoff = datetime.now(UTC) - timedelta(days=1)
    await session.execute(delete(OAuthState).where(OAuthState.expires_at < cutoff))
    await session.execute(
        delete(OAuthHandoffCode).where(OAuthHandoffCode.expires_at < cutoff)
    )


async def create_oauth_handoff(
    session: AsyncSession,
    *,
    provider: str,
    code_hash: str,
    user_id: uuid.UUID,
    expires_at: datetime,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> OAuthHandoffCode:
    handoff = OAuthHandoffCode(
        provider=provider,
        code_hash=code_hash,
        user_id=user_id,
        expires_at=expires_at,
        user_agent=(user_agent or "")[:512] or None,
        ip_address=(ip_address or "")[:64] or None,
    )
    session.add(handoff)
    await session.flush()
    return handoff


async def consume_oauth_handoff(
    session: AsyncSession, *, provider: str, code_hash: str
) -> OAuthHandoffCode | None:
    """Atomically consume a handoff code exactly once."""

    handoff = await session.scalar(
        select(OAuthHandoffCode).where(
            OAuthHandoffCode.provider == provider,
            OAuthHandoffCode.code_hash == code_hash,
        )
    )
    if handoff is None:
        return None
    now = datetime.now(UTC)
    expires_at = as_utc(handoff.expires_at)
    if handoff.used_at is not None or expires_at is None or expires_at <= now:
        return None
    result = await session.execute(
        update(OAuthHandoffCode)
        .where(OAuthHandoffCode.id == handoff.id, OAuthHandoffCode.used_at.is_(None))
        .values(used_at=now)
    )
    if not result.rowcount:
        return None
    await session.flush()
    return handoff


async def create_refresh_token(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    token_hash: str,
    expires_at: datetime,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> RefreshToken:
    token = RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
        user_agent=(user_agent or "")[:512] or None,
        ip_address=(ip_address or "")[:64] or None,
    )
    session.add(token)
    await session.flush()
    return token


async def find_refresh_token(session: AsyncSession, token_hash: str) -> RefreshToken | None:
    return await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )


async def revoke_refresh_token(session: AsyncSession, token: RefreshToken) -> None:
    token.revoked_at = datetime.now(UTC)
    await session.flush()


async def revoke_all_tokens(session: AsyncSession, user_id: uuid.UUID) -> None:
    tokens = await session.scalars(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
        )
    )
    now = datetime.now(UTC)
    for token in tokens:
        token.revoked_at = now
    await session.flush()


async def list_bookmarks(session: AsyncSession, user_id: uuid.UUID) -> list[Bookmark]:
    result = await session.scalars(
        select(Bookmark)
        .where(Bookmark.user_id == user_id)
        .order_by(Bookmark.created_at.desc())
    )
    return list(result.all())


async def get_bookmark(
    session: AsyncSession, user_id: uuid.UUID, manga_id: uuid.UUID
) -> Bookmark | None:
    return await session.scalar(
        select(Bookmark).where(Bookmark.user_id == user_id, Bookmark.manga_id == manga_id)
    )


async def add_bookmark(
    session: AsyncSession, user_id: uuid.UUID, manga_id: uuid.UUID
) -> tuple[Bookmark, bool]:
    existing = await get_bookmark(session, user_id, manga_id)
    if existing:
        return existing, False
    bookmark = Bookmark(user_id=user_id, manga_id=manga_id)
    session.add(bookmark)
    await session.flush()
    return bookmark, True


async def remove_bookmark(
    session: AsyncSession, user_id: uuid.UUID, manga_id: uuid.UUID
) -> bool:
    result = await session.execute(
        delete(Bookmark).where(Bookmark.user_id == user_id, Bookmark.manga_id == manga_id)
    )
    return bool(result.rowcount)


async def list_progress(
    session: AsyncSession, user_id: uuid.UUID, limit: int = 100
) -> list[ReadingProgress]:
    result = await session.scalars(
        select(ReadingProgress)
        .where(ReadingProgress.user_id == user_id)
        .order_by(ReadingProgress.updated_at.desc())
        .limit(limit)
    )
    return list(result.all())


async def get_progress(
    session: AsyncSession, user_id: uuid.UUID, manga_id: uuid.UUID
) -> ReadingProgress | None:
    return await session.scalar(
        select(ReadingProgress).where(
            ReadingProgress.user_id == user_id, ReadingProgress.manga_id == manga_id
        )
    )


async def upsert_progress(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    manga_id: uuid.UUID,
    chapter_id: uuid.UUID,
    page: int,
    total_pages: int,
) -> ReadingProgress:
    progress = await get_progress(session, user_id, manga_id)
    if progress is None:
        progress = ReadingProgress(
            user_id=user_id,
            manga_id=manga_id,
            chapter_id=chapter_id,
            page=page,
            total_pages=total_pages,
        )
        session.add(progress)
    else:
        progress.chapter_id = chapter_id
        progress.page = page
        progress.total_pages = total_pages
        progress.updated_at = datetime.now(UTC)
    await session.flush()
    return progress


async def delete_progress(
    session: AsyncSession, user_id: uuid.UUID, manga_id: uuid.UUID
) -> bool:
    result = await session.execute(
        delete(ReadingProgress).where(
            ReadingProgress.user_id == user_id, ReadingProgress.manga_id == manga_id
        )
    )
    return bool(result.rowcount)


async def get_settings(session: AsyncSession, user_id: uuid.UUID) -> UserSettings | None:
    return await session.scalar(select(UserSettings).where(UserSettings.user_id == user_id))


async def upsert_settings(
    session: AsyncSession, user_id: uuid.UUID, data: dict[str, Any]
) -> UserSettings:
    settings = await get_settings(session, user_id)
    if settings is None:
        settings = UserSettings(user_id=user_id, data=data)
        session.add(settings)
    else:
        settings.data = data
    await session.flush()
    return settings


async def merge_progress(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    items: list[tuple[uuid.UUID, uuid.UUID, int, int, datetime]],
) -> tuple[int, int, int]:
    """Merge device-local positions into the account.

    Returns ``(merged, unchanged, ignored)``.  Positions older than the stored
    account copy are ignored, so a stale offline device can never rewind the
    user's real progress.  Input duplicates are resolved client-side, but the
    repository is defensive and keeps the newest entry per manga.
    """

    now = datetime.now(UTC)
    newest: dict[uuid.UUID, tuple[uuid.UUID, int, int, datetime]] = {}
    for manga_id, chapter_id, page, total_pages, read_at in items:
        moment = as_utc(read_at)
        if moment is None:
            continue
        # A device with a wrong clock must not create a future reading day.
        moment = min(moment, now)
        current = newest.get(manga_id)
        if current is None or moment > current[3]:
            newest[manga_id] = (chapter_id, page, total_pages, moment)

    merged = 0
    unchanged = 0
    for manga_id, (chapter_id, page, total_pages, moment) in newest.items():
        existing = await get_progress(session, user_id, manga_id)
        await record_reading_day(session, user_id=user_id, read_at=moment)
        if existing is None:
            session.add(
                ReadingProgress(
                    user_id=user_id,
                    manga_id=manga_id,
                    chapter_id=chapter_id,
                    page=page,
                    total_pages=total_pages,
                    created_at=moment,
                    updated_at=moment,
                )
            )
            merged += 1
            continue
        current_at = as_utc(existing.updated_at) or datetime.min.replace(tzinfo=UTC)
        if moment <= current_at:
            unchanged += 1
            continue
        existing.chapter_id = chapter_id
        existing.page = page
        existing.total_pages = total_pages
        existing.updated_at = moment
        merged += 1
    await session.flush()
    return merged, unchanged, len(items) - len(newest)


async def insert_analytics_events(
    session: AsyncSession, rows: list[dict[str, Any]]
) -> tuple[int, int]:
    """Insert events idempotently and return ``(accepted, duplicates)``."""

    if not rows:
        return 0, 0
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        statement = postgres_insert(AnalyticsEvent).values(rows)
        statement = statement.on_conflict_do_nothing(index_elements=["dedupe_key"])
        result = await session.execute(statement)
        accepted = int(result.rowcount or 0)
    elif dialect == "sqlite":
        statement = sqlite_insert(AnalyticsEvent).values(rows)
        statement = statement.on_conflict_do_nothing(index_elements=["dedupe_key"])
        result = await session.execute(statement)
        accepted = int(result.rowcount or 0)
    else:
        keys = [str(row["dedupe_key"]) for row in rows]
        existing = set(
            (await session.scalars(select(AnalyticsEvent.dedupe_key).where(
                AnalyticsEvent.dedupe_key.in_(keys)
            ))).all()
        )
        prepared = [row for row in rows if row["dedupe_key"] not in existing]
        session.add_all([AnalyticsEvent(**row) for row in prepared])
        accepted = len(prepared)
    await session.flush()
    return accepted, max(0, len(rows) - accepted)


async def list_analytics_events(
    session: AsyncSession, *, since: datetime
) -> list[AnalyticsEvent]:
    result = await session.scalars(
        select(AnalyticsEvent)
        .where(AnalyticsEvent.created_at >= since)
        .order_by(AnalyticsEvent.created_at.asc())
    )
    return list(result.all())


async def analytics_surface_totals(
    session: AsyncSession, *, since: datetime
) -> list[tuple[str, str, int]]:
    """Impression/click counts grouped by non-empty product surface."""

    rows = await session.execute(
        select(AnalyticsEvent.surface, AnalyticsEvent.event, func.count(AnalyticsEvent.id))
        .where(
            AnalyticsEvent.created_at >= since,
            AnalyticsEvent.event.in_(("impression", "click")),
            AnalyticsEvent.surface != "",
        )
        .group_by(AnalyticsEvent.surface, AnalyticsEvent.event)
    )
    return [(str(row[0]), str(row[1]), int(row[2])) for row in rows.all()]


async def record_traffic_visit(
    session: AsyncSession,
    *,
    visitor_hash: str,
    path_group: str,
    visited_at: datetime | None = None,
) -> bool:
    """Insert one visitor/day row; return ``True`` only for a new visitor.

    The unique constraint is the deduplication guarantee.  The dialect-specific
    ``ON CONFLICT DO NOTHING`` keeps page-view beacons cheap even when a reader
    opens several pages in one day.
    """

    moment = as_utc(visited_at) or datetime.now(UTC)
    row = {
        "visitor_hash": visitor_hash,
        "day": moment.astimezone(UTC).date(),
        "path_group": path_group,
        "created_at": moment,
    }
    dialect = session.get_bind().dialect.name
    if dialect in {"postgresql", "sqlite"}:
        insert = postgres_insert if dialect == "postgresql" else sqlite_insert
        statement = insert(TrafficVisit).values(row)
        statement = statement.on_conflict_do_nothing(
            index_elements=["visitor_hash", "day"]
        )
        result = await session.execute(statement)
        accepted = int(result.rowcount or 0) > 0
    else:
        existing = await session.scalar(
            select(TrafficVisit.id).where(
                TrafficVisit.visitor_hash == visitor_hash,
                TrafficVisit.day == row["day"],
            )
        )
        accepted = existing is None
        if accepted:
            session.add(TrafficVisit(**row))
    await session.flush()
    return accepted


async def traffic_unique_visitors(
    session: AsyncSession, *, since_day: date, until_day: date
) -> int:
    value = await session.scalar(
        select(func.count(func.distinct(TrafficVisit.visitor_hash))).where(
            TrafficVisit.day >= since_day,
            TrafficVisit.day <= until_day,
        )
    )
    return int(value or 0)


async def traffic_daily_counts(
    session: AsyncSession, *, since_day: date, until_day: date
) -> dict[date, int]:
    rows = await session.execute(
        select(TrafficVisit.day, func.count(TrafficVisit.id))
        .where(
            TrafficVisit.day >= since_day,
            TrafficVisit.day <= until_day,
        )
        .group_by(TrafficVisit.day)
        .order_by(TrafficVisit.day.asc())
    )
    return {row[0]: int(row[1]) for row in rows.all()}


async def traffic_path_groups(
    session: AsyncSession, *, since_day: date, until_day: date
) -> list[tuple[str, int]]:
    rows = await session.execute(
        select(
            TrafficVisit.path_group,
            func.count(func.distinct(TrafficVisit.visitor_hash)),
        )
        .where(
            TrafficVisit.day >= since_day,
            TrafficVisit.day <= until_day,
        )
        .group_by(TrafficVisit.path_group)
        .order_by(
            func.count(func.distinct(TrafficVisit.visitor_hash)).desc(),
            TrafficVisit.path_group.asc(),
        )
    )
    return [(str(row[0]), int(row[1])) for row in rows.all()]


async def traffic_last_visit(session: AsyncSession) -> datetime | None:
    return as_utc(await session.scalar(select(func.max(TrafficVisit.created_at))))


async def purge_traffic_visits(session: AsyncSession, *, before_day: date) -> int:
    result = await session.execute(delete(TrafficVisit).where(TrafficVisit.day < before_day))
    await session.flush()
    return int(result.rowcount or 0)
