from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from manga_common.auth import (
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    password_needs_rehash,
    refresh_expiry,
    verify_password,
)
from manga_common.errors import ConflictError, NotFoundError, UnauthorizedError
from manga_common.schemas import (
    AnalyticsEventIn,
    AnalyticsIngestOut,
    AnalyticsRetentionOut,
    BookmarkOut,
    ProgressMergeItem,
    ProgressMergeOut,
    ProgressOut,
    ReaderSettings,
    StreakOut,
    TokenPair,
    UserOut,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .analytics import compute_retention
from .config import LibrarySettings
from .models import User
from .profile_repository import ensure_user_profile
from .profiles import ProgressActivity, record_progress_activity
from .repository import (
    add_bookmark,
    as_utc,
    create_refresh_token,
    create_user,
    delete_progress,
    find_refresh_token,
    get_progress,
    get_settings,
    get_user,
    get_user_by_email,
    insert_analytics_events,
    list_analytics_events,
    list_bookmarks,
    list_progress,
    list_reading_days,
    merge_progress,
    record_reading_day,
    remove_bookmark,
    revoke_all_tokens,
    revoke_refresh_token,
    upsert_progress,
    upsert_settings,
)
from .streak import compute_streak

logger = logging.getLogger(__name__)


def _user_out(user: User) -> UserOut:
    return UserOut.model_validate(user)


class LibraryService:
    def __init__(
        self,
        settings: LibrarySettings,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory

    async def _issue_tokens(
        self,
        session: AsyncSession,
        user: User,
        *,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> TokenPair:
        access, expires_in = create_access_token(
            self.settings,
            subject=str(user.id),
            role=user.role,
            extra={"display_name": user.display_name, "username": user.display_name},
        )
        refresh = new_refresh_token()
        await create_refresh_token(
            session,
            user_id=user.id,
            token_hash=hash_refresh_token(refresh),
            expires_at=refresh_expiry(self.settings),
            user_agent=user_agent,
            ip_address=ip_address,
        )
        return TokenPair(
            access_token=access,
            refresh_token=refresh,
            expires_in=expires_in,
            user=_user_out(user),
        )

    async def register(
        self,
        *,
        email: str,
        password: str,
        display_name: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> TokenPair:
        async with self.session_factory() as session:
            if await get_user_by_email(session, email):
                raise ConflictError("Пользователь с таким email уже существует", code="email_taken")
            try:
                user = await create_user(
                    session,
                    email=email,
                    password_hash=hash_password(password),
                    display_name=display_name,
                )
                await ensure_user_profile(session, user)
            except IntegrityError as exc:
                await session.rollback()
                raise ConflictError(
                    "Пользователь с таким email уже существует", code="email_taken"
                ) from exc
            tokens = await self._issue_tokens(
                session, user, user_agent=user_agent, ip_address=ip_address
            )
            await session.commit()
            return tokens

    async def login(
        self,
        *,
        email: str,
        password: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> TokenPair:
        async with self.session_factory() as session:
            user = await get_user_by_email(session, email)
            if user is None or not user.is_active or not verify_password(password, user.password_hash):
                raise UnauthorizedError("Неверный email или пароль", code="invalid_credentials")
            if password_needs_rehash(user.password_hash):
                user.password_hash = hash_password(password)
            await ensure_user_profile(session, user)
            tokens = await self._issue_tokens(
                session, user, user_agent=user_agent, ip_address=ip_address
            )
            await session.commit()
            return tokens

    async def refresh(self, refresh_token: str) -> TokenPair:
        token_hash = hash_refresh_token(refresh_token)
        async with self.session_factory() as session:
            stored = await find_refresh_token(session, token_hash)
            if stored is None:
                raise UnauthorizedError("Refresh token не найден", code="invalid_refresh_token")
            expires_at = as_utc(stored.expires_at)
            if stored.revoked_at is not None:
                raise UnauthorizedError("Refresh token отозван", code="refresh_revoked")
            if expires_at is None or expires_at <= datetime.now(UTC):
                raise UnauthorizedError("Refresh token истёк", code="refresh_expired")
            user = await get_user(session, stored.user_id)
            if user is None or not user.is_active:
                raise UnauthorizedError("Пользователь не найден", code="invalid_user")
            await ensure_user_profile(session, user)
            await revoke_refresh_token(session, stored)
            tokens = await self._issue_tokens(session, user)
            await session.commit()
            return tokens

    async def logout(self, refresh_token: str) -> None:
        token_hash = hash_refresh_token(refresh_token)
        async with self.session_factory() as session:
            stored = await find_refresh_token(session, token_hash)
            if stored is not None and stored.revoked_at is None:
                await revoke_refresh_token(session, stored)
                await session.commit()

    async def me(self, user_id: uuid.UUID) -> UserOut:
        async with self.session_factory() as session:
            user = await get_user(session, user_id)
            if user is None or not user.is_active:
                raise UnauthorizedError("Пользователь не найден", code="invalid_user")
            await ensure_user_profile(session, user)
            await session.commit()
            return _user_out(user)

    async def bookmarks(self, user_id: uuid.UUID) -> list[BookmarkOut]:
        async with self.session_factory() as session:
            rows = await list_bookmarks(session, user_id)
            return [BookmarkOut.model_validate(row) for row in rows]

    async def add_bookmark(self, user_id: uuid.UUID, manga_id: uuid.UUID) -> BookmarkOut:
        async with self.session_factory() as session:
            bookmark, created = await add_bookmark(session, user_id, manga_id)
            await session.commit()
            if created:
                logger.info("bookmark added", extra={"user_id": str(user_id)})
            return BookmarkOut.model_validate(bookmark)

    async def remove_bookmark(self, user_id: uuid.UUID, manga_id: uuid.UUID) -> bool:
        async with self.session_factory() as session:
            removed = await remove_bookmark(session, user_id, manga_id)
            await session.commit()
            return removed

    async def history(self, user_id: uuid.UUID, limit: int = 100) -> list[ProgressOut]:
        async with self.session_factory() as session:
            rows = await list_progress(session, user_id, limit=limit)
            return [ProgressOut.model_validate(row) for row in rows]

    async def progress(self, user_id: uuid.UUID, manga_id: uuid.UUID) -> ProgressOut:
        async with self.session_factory() as session:
            row = await get_progress(session, user_id, manga_id)
            if row is None:
                raise NotFoundError("Прогресс не найден")
            return ProgressOut.model_validate(row)

    async def upsert_progress(
        self,
        user_id: uuid.UUID,
        *,
        manga_id: uuid.UUID,
        chapter_id: uuid.UUID,
        page: int,
        total_pages: int,
        activity: ProgressActivity | None = None,
    ) -> ProgressOut:
        async with self.session_factory() as session:
            row = await upsert_progress(
                session,
                user_id=user_id,
                manga_id=manga_id,
                chapter_id=chapter_id,
                page=page,
                total_pages=total_pages,
            )
            now = datetime.now(UTC)
            await record_reading_day(session, user_id=user_id, read_at=now)
            if activity is not None:
                await record_progress_activity(
                    session, user_id=user_id, activity=activity, now=now
                )
            await session.commit()
            return ProgressOut.model_validate(row)

    async def merge_local_progress(
        self,
        user_id: uuid.UUID,
        items: list[ProgressMergeItem],
        read_days: list[datetime] | None = None,
    ) -> ProgressMergeOut:
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            merged, unchanged, ignored = await merge_progress(
                session,
                user_id=user_id,
                items=[
                    (
                        item.manga_id,
                        item.chapter_id,
                        item.page,
                        item.total_pages,
                        item.read_at,
                    )
                    for item in items
                ],
            )
            for moment in read_days or []:
                normalized = as_utc(moment)
                if normalized is not None:
                    await record_reading_day(
                        session, user_id=user_id, read_at=min(normalized, now)
                    )
            await session.commit()
            return ProgressMergeOut(merged=merged, unchanged=unchanged, ignored=ignored)

    async def streak(self, user_id: uuid.UUID, timezone: str | None) -> StreakOut:
        async with self.session_factory() as session:
            rows = await list_reading_days(session, user_id)
            return compute_streak(
                [row.last_read_at for row in rows],
                timezone=timezone,
                now=datetime.now(UTC),
            )

    async def ingest_analytics(self, events: list[AnalyticsEventIn]) -> AnalyticsIngestOut:
        rows = [
            {
                "event": event.event,
                "client_id": event.client_id,
                "surface": event.surface,
                "manga_id": event.manga_id,
                "chapter_id": event.chapter_id,
                "dedupe_key": event.dedupe_key,
                "created_at": datetime.now(UTC),
            }
            for event in events
        ]
        async with self.session_factory() as session:
            accepted, duplicates = await insert_analytics_events(session, rows)
            await session.commit()
            return AnalyticsIngestOut(accepted=accepted, duplicates=duplicates)

    async def analytics_retention(self, days: int = 30) -> AnalyticsRetentionOut:
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            events = await list_analytics_events(
                session, since=now - timedelta(days=max(1, min(days, 90)) + 30)
            )
        return compute_retention(events, days=days, now=now)

    async def delete_progress(self, user_id: uuid.UUID, manga_id: uuid.UUID) -> bool:
        async with self.session_factory() as session:
            removed = await delete_progress(session, user_id, manga_id)
            await session.commit()
            return removed

    async def reader_settings(self, user_id: uuid.UUID) -> ReaderSettings:
        async with self.session_factory() as session:
            row = await get_settings(session, user_id)
            data = (row.data if row else {}) or {}
            return ReaderSettings.model_validate({**ReaderSettings().model_dump(), **data})

    async def save_reader_settings(
        self, user_id: uuid.UUID, settings: ReaderSettings
    ) -> ReaderSettings:
        async with self.session_factory() as session:
            await upsert_settings(session, user_id, settings.model_dump())
            await session.commit()
            return settings

    async def revoke_all(self, user_id: uuid.UUID) -> None:
        async with self.session_factory() as session:
            await revoke_all_tokens(session, user_id)
            await session.commit()
