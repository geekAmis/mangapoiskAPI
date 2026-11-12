from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    ProfileBlock,
    ProfileEvent,
    ProfileReport,
    ReadingDay,
    User,
    UserAchievement,
    UserProfile,
    XpEvent,
)

USERNAME_PATTERN = re.compile(r"^[a-z0-9_]{3,24}$")
RESERVED_USERNAMES = {
    "admin",
    "administrator",
    "api",
    "me",
    "moderator",
    "moderation",
    "null",
    "profile",
    "profiles",
    "root",
    "settings",
    "support",
    "system",
    "u",
    "undefined",
    "user",
}

_TRANSLITERATION = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "c",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def slug_base(value: str) -> str:
    """Transliterate a display name into a short URL-safe handle."""

    result: list[str] = []
    for character in value.lower():
        if character in _TRANSLITERATION:
            result.append(_TRANSLITERATION[character])
            continue
        decomposed = unicodedata.normalize("NFKD", character)
        ascii_character = decomposed.encode("ascii", "ignore").decode()
        if ascii_character:
            result.append(ascii_character)
    text = re.sub(r"[^a-z0-9]+", "_", "".join(result)).strip("_")
    return (text[:18] or "reader").strip("_") or "reader"


async def _insert_ignore(
    session: AsyncSession,
    model: Any,
    values: dict[str, Any],
    *index_elements: str,
) -> bool:
    """Insert one row and return True only when it was actually created."""

    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        statement = postgres_insert(model).values(**values)
        statement = statement.on_conflict_do_nothing(index_elements=list(index_elements))
        result = await session.execute(statement)
        return bool(result.rowcount)
    if dialect == "sqlite":
        statement = sqlite_insert(model).values(**values)
        statement = statement.on_conflict_do_nothing(index_elements=list(index_elements))
        result = await session.execute(statement)
        return bool(result.rowcount)

    conditions = [getattr(model, key) == value for key, value in values.items() if key in index_elements]
    existing = await session.scalar(select(model.id).where(*conditions))
    if existing is not None:
        return False
    session.add(model(**values))
    await session.flush()
    return True


async def ensure_user_profile(session: AsyncSession, user: User) -> UserProfile:
    """Return the profile row, creating a deterministic handle when absent.

    Existing accounts are handled lazily on first access, so deploying this
    feature needs no data migration.  The short id suffix keeps generated
    handles unique without a display-name reservation race.
    """

    profile = await session.scalar(
        select(UserProfile).where(UserProfile.user_id == user.id)
    )
    if profile is not None:
        return profile

    base = slug_base(user.display_name)
    suffix = user.id.hex[:8]
    for attempt in range(8):
        candidate = f"{base[:15]}_{suffix}" if attempt == 0 else f"{base[:13]}_{suffix}{attempt}"
        if len(candidate) > 24:
            candidate = candidate[:24].rstrip("_")
        if candidate in RESERVED_USERNAMES:
            candidate = f"{candidate}_{suffix}"[:24]
        taken = await session.scalar(
            select(UserProfile.id).where(UserProfile.username == candidate)
        )
        if taken is not None:
            continue
        # ON CONFLICT (user_id) makes concurrent first visits for the same
        # account safe: the loser of the race simply reads the winning row.
        created = await _insert_ignore(
            session,
            UserProfile,
            {
                "id": uuid.uuid4(),
                "user_id": user.id,
                "username": candidate,
            },
            "user_id",
        )
        if created:
            return await get_profile(session, user.id)  # type: ignore[return-value]
        existing = await get_profile(session, user.id)
        if existing is not None:
            return existing
    raise RuntimeError("could not allocate a unique username")


async def get_profile(session: AsyncSession, user_id: uuid.UUID) -> UserProfile | None:
    return await session.scalar(select(UserProfile).where(UserProfile.user_id == user_id))


async def get_user_by_username(session: AsyncSession, username: str) -> User | None:
    return await session.scalar(
        select(User)
        .join(UserProfile, UserProfile.user_id == User.id)
        .where(UserProfile.username == username.lower())
    )


async def username_taken(
    session: AsyncSession, username: str, *, exclude_user_id: uuid.UUID | None = None
) -> bool:
    statement = select(UserProfile.id).where(UserProfile.username == username)
    if exclude_user_id is not None:
        statement = statement.where(UserProfile.user_id != exclude_user_id)
    return await session.scalar(statement) is not None


async def get_xp_total(session: AsyncSession, user_id: uuid.UUID) -> int:
    total = await session.scalar(
        select(func.coalesce(func.sum(XpEvent.xp), 0)).where(XpEvent.user_id == user_id)
    )
    return int(total or 0)


async def chapter_xp_since(
    session: AsyncSession, user_id: uuid.UUID, since: datetime
) -> int:
    total = await session.scalar(
        select(func.coalesce(func.sum(XpEvent.xp), 0)).where(
            XpEvent.user_id == user_id,
            XpEvent.source == "chapter",
            XpEvent.created_at >= since,
        )
    )
    return int(total or 0)


async def add_xp_event(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    source: str,
    dedupe_key: str,
    xp: int,
    manga_id: uuid.UUID | None = None,
    chapter_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> bool:
    return await _insert_ignore(
        session,
        XpEvent,
        {
            "id": uuid.uuid4(),
            "user_id": user_id,
            "source": source,
            "dedupe_key": dedupe_key,
            "xp": max(0, int(xp)),
            "manga_id": manga_id,
            "chapter_id": chapter_id,
            "created_at": created_at or datetime.now(UTC),
        },
        "user_id",
        "dedupe_key",
    )


async def add_profile_event(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: str,
    dedupe_key: str,
    manga_id: uuid.UUID | None = None,
    chapter_id: uuid.UUID | None = None,
    manga_title: str | None = None,
    chapter_label: str | None = None,
    poster_url: str | None = None,
    genres: list[str] | None = None,
    achievement_code: str | None = None,
    created_at: datetime | None = None,
) -> bool:
    return await _insert_ignore(
        session,
        ProfileEvent,
        {
            "id": uuid.uuid4(),
            "user_id": user_id,
            "kind": kind,
            "dedupe_key": dedupe_key,
            "manga_id": manga_id,
            "chapter_id": chapter_id,
            "manga_title": (manga_title or "")[:255] or None,
            "chapter_label": (chapter_label or "")[:128] or None,
            "poster_url": (poster_url or "")[:1024] or None,
            "genres": [str(item)[:48] for item in (genres or [])][:8],
            "achievement_code": (achievement_code or "")[:48] or None,
            "created_at": created_at or datetime.now(UTC),
        },
        "user_id",
        "dedupe_key",
    )


async def unlock_achievement(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    code: str,
    unlocked_at: datetime | None = None,
) -> bool:
    return await _insert_ignore(
        session,
        UserAchievement,
        {
            "id": uuid.uuid4(),
            "user_id": user_id,
            "code": code,
            "unlocked_at": unlocked_at or datetime.now(UTC),
        },
        "user_id",
        "code",
    )


async def list_unlocked_achievements(
    session: AsyncSession, user_id: uuid.UUID
) -> dict[str, datetime]:
    rows = await session.scalars(
        select(UserAchievement).where(UserAchievement.user_id == user_id)
    )
    return {row.code: row.unlocked_at for row in rows.all()}


async def count_unlocked_achievements(session: AsyncSession, user_id: uuid.UUID) -> int:
    total = await session.scalar(
        select(func.count(UserAchievement.id)).where(UserAchievement.user_id == user_id)
    )
    return int(total or 0)


async def count_profile_events(
    session: AsyncSession, user_id: uuid.UUID, kind: str | None = None
) -> int:
    statement = select(func.count(ProfileEvent.id)).where(ProfileEvent.user_id == user_id)
    if kind:
        statement = statement.where(ProfileEvent.kind == kind)
    total = await session.scalar(statement)
    return int(total or 0)


async def count_distinct_titles(session: AsyncSession, user_id: uuid.UUID) -> int:
    total = await session.scalar(
        select(func.count(func.distinct(ProfileEvent.manga_id))).where(
            ProfileEvent.user_id == user_id,
            ProfileEvent.kind == "chapter_read",
            ProfileEvent.manga_id.is_not(None),
        )
    )
    return int(total or 0)


async def count_reading_days(session: AsyncSession, user_id: uuid.UUID) -> int:
    total = await session.scalar(
        select(func.count(ReadingDay.id)).where(ReadingDay.user_id == user_id)
    )
    return int(total or 0)


async def list_profile_events(
    session: AsyncSession, user_id: uuid.UUID, limit: int = 30
) -> list[ProfileEvent]:
    result = await session.scalars(
        select(ProfileEvent)
        .where(ProfileEvent.user_id == user_id)
        .order_by(ProfileEvent.created_at.desc())
        .limit(limit)
    )
    return list(result.all())


async def favorite_genres(
    session: AsyncSession, user_id: uuid.UUID, limit: int = 5
) -> list[tuple[str, int]]:
    """Count genres once per distinct title, not once per chapter."""

    rows = await session.scalars(
        select(ProfileEvent)
        .where(
            ProfileEvent.user_id == user_id,
            ProfileEvent.kind == "chapter_read",
            ProfileEvent.manga_id.is_not(None),
        )
        .order_by(ProfileEvent.created_at.desc())
        .limit(500)
    )
    seen: set[uuid.UUID] = set()
    counts: dict[str, int] = {}
    for row in rows.all():
        if row.manga_id in seen:
            continue
        seen.add(row.manga_id)
        for genre in (row.genres or [])[:8]:
            value = str(genre).strip()
            if value:
                counts[value] = counts.get(value, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))
    return ordered[:limit]


async def update_profile_fields(
    session: AsyncSession, profile: UserProfile, values: dict[str, Any]
) -> UserProfile:
    for key, value in values.items():
        setattr(profile, key, value)
    await session.flush()
    return profile


async def find_open_report(
    session: AsyncSession, reporter_id: uuid.UUID, target_user_id: uuid.UUID
) -> ProfileReport | None:
    return await session.scalar(
        select(ProfileReport).where(
            ProfileReport.reporter_id == reporter_id,
            ProfileReport.target_user_id == target_user_id,
            ProfileReport.status == "open",
        )
    )


async def create_report(
    session: AsyncSession,
    *,
    reporter_id: uuid.UUID,
    target_user_id: uuid.UUID,
    reason: str,
    created_at: datetime | None = None,
) -> ProfileReport:
    report = ProfileReport(
        reporter_id=reporter_id,
        target_user_id=target_user_id,
        reason=reason[:500],
        status="open",
        created_at=created_at or datetime.now(UTC),
    )
    session.add(report)
    await session.flush()
    return report


async def list_reports(
    session: AsyncSession, status: str = "open", limit: int = 50
) -> list[ProfileReport]:
    statement = select(ProfileReport)
    if status != "all":
        statement = statement.where(ProfileReport.status == status)
    result = await session.scalars(
        statement.order_by(ProfileReport.created_at.desc()).limit(limit)
    )
    return list(result.all())


async def get_report(
    session: AsyncSession, report_id: uuid.UUID
) -> ProfileReport | None:
    return await session.get(ProfileReport, report_id)


async def resolve_report(
    session: AsyncSession, report: ProfileReport, status: str
) -> ProfileReport:
    report.status = status
    report.resolved_at = datetime.now(UTC)
    await session.flush()
    return report


async def is_blocked(
    session: AsyncSession, first: uuid.UUID, second: uuid.UUID
) -> bool:
    """True when either user blocked the other; blocks are mutually invisible."""

    found = await session.scalar(
        select(ProfileBlock.id).where(
            ((ProfileBlock.blocker_id == first) & (ProfileBlock.blocked_id == second))
            | ((ProfileBlock.blocker_id == second) & (ProfileBlock.blocked_id == first))
        )
    )
    return found is not None


async def set_block(
    session: AsyncSession, blocker_id: uuid.UUID, blocked_id: uuid.UUID, blocked: bool
) -> None:
    if blocked:
        await _insert_ignore(
            session,
            ProfileBlock,
            {
                "id": uuid.uuid4(),
                "blocker_id": blocker_id,
                "blocked_id": blocked_id,
                "created_at": datetime.now(UTC),
            },
            "blocker_id",
            "blocked_id",
        )
        return
    await session.execute(
        delete(ProfileBlock).where(
            ProfileBlock.blocker_id == blocker_id, ProfileBlock.blocked_id == blocked_id
        )
    )
    await session.flush()


def utc_day_start(moment: datetime) -> datetime:
    day: date = moment.astimezone(UTC).date()
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def utc_day_key(moment: datetime) -> str:
    return f"day:{moment.astimezone(UTC).date().isoformat()}"


def chapter_key(chapter_id: uuid.UUID) -> str:
    return f"chapter:{chapter_id}"


def finish_key(manga_id: uuid.UUID) -> str:
    return f"finish:{manga_id}"


def achievement_key(code: str) -> str:
    return f"achievement:{code}"


def today_start(now: datetime) -> datetime:
    return utc_day_start(now)


def as_date(value: datetime | None) -> date:
    moment = as_utc(value) or datetime.now(UTC)
    return moment.astimezone(UTC).date()


def recent_cutoff(days: int = 30) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)
