from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Bookmark, ReadingProgress, RefreshToken, User, UserSettings


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(select(User).where(User.email == email.lower().strip()))


async def create_user(
    session: AsyncSession, *, email: str, password_hash: str, display_name: str
) -> User:
    user = User(
        email=email.lower().strip(),
        password_hash=password_hash,
        display_name=display_name.strip(),
    )
    session.add(user)
    await session.flush()
    session.add(UserSettings(user_id=user.id, data={}))
    await session.flush()
    return user


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
