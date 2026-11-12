from __future__ import annotations

import logging
import math
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from manga_common.errors import ConflictError, NotFoundError, ValidationError
from manga_common.profile_schemas import (
    AchievementOut,
    AdminProfileReportOut,
    GenreCountOut,
    MyProfileOut,
    ProfileEventOut,
    ProfilePrivacyOut,
    ProfileReportOut,
    ProfileStatsOut,
    ProfileUpdate,
    PublicProfileOut,
    RankOut,
)
from manga_common.schemas import OkResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config import LibrarySettings
from .models import ProfileEvent, User, UserProfile
from .profile_repository import (
    RESERVED_USERNAMES,
    USERNAME_PATTERN,
    achievement_key,
    add_profile_event,
    add_xp_event,
    as_date,
    as_utc,
    chapter_key,
    chapter_xp_since,
    count_distinct_titles,
    count_profile_events,
    count_reading_days,
    create_report,
    ensure_user_profile,
    favorite_genres,
    find_open_report,
    finish_key,
    get_profile,
    get_report,
    get_user_by_username,
    get_xp_total,
    is_blocked,
    list_profile_events,
    list_reports,
    list_unlocked_achievements,
    resolve_report,
    set_block,
    today_start,
    update_profile_fields,
    username_taken,
    utc_day_key,
)
from .repository import get_user, list_reading_days
from .streak import compute_streak

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Transparent gamification rules (see docs/PROFILES.md)
# ---------------------------------------------------------------------------

CHAPTER_XP = 10
DAY_XP = 5
FINISH_XP = 25
CHAPTER_DAILY_CAP = 100
MAX_LEVEL = 99

# Cumulative XP required to reach a level: 25 * L * (L - 1).
# L2 = 50, L3 = 150, L4 = 300, L10 = 2250, L20 = 9500.
LEVEL_STEP = 25


def xp_for_level(level: int) -> int:
    level = max(1, min(int(level), MAX_LEVEL))
    return LEVEL_STEP * level * (level - 1)


def level_for_xp(xp: int) -> int:
    xp = max(0, int(xp))
    level = int((1 + math.isqrt(1 + 4 * xp // LEVEL_STEP)) // 2)
    while xp_for_level(level + 1) <= xp and level < MAX_LEVEL:
        level += 1
    while level > 1 and xp_for_level(level) > xp:
        level -= 1
    return max(1, min(level, MAX_LEVEL))


@dataclass(frozen=True, slots=True)
class Rank:
    code: str
    label: str
    min_level: int


RANKS: tuple[Rank, ...] = (
    Rank("reader", "Читатель", 1),
    Rank("regular", "Постоянный читатель", 3),
    Rank("enthusiast", "Манга-энтузиаст", 5),
    Rank("senpai", "Сэмпай", 8),
    Rank("sensei", "Сенсей", 12),
    Rank("storyteller", "Мастер историй", 17),
    Rank("legend", "Легенда MangaPoisk", 25),
)


def rank_for_level(level: int) -> Rank:
    result = RANKS[0]
    for rank in RANKS:
        if level >= rank.min_level:
            result = rank
        else:
            break
    return result


def next_rank_for_level(level: int) -> Rank | None:
    for rank in RANKS:
        if level < rank.min_level:
            return rank
    return None


@dataclass(frozen=True, slots=True)
class Achievement:
    code: str
    title: str
    description: str
    icon: str
    metric: str
    target: int


ACHIEVEMENTS: tuple[Achievement, ...] = (
    Achievement("first_chapter", "Первая глава", "Прочитайте первую главу", "book", "chapters", 1),
    Achievement("ten_chapters", "Десять глав", "Прочитайте 10 глав", "book", "chapters", 10),
    Achievement("fifty_chapters", "Пятьдесят глав", "Прочитайте 50 глав", "book", "chapters", 50),
    Achievement("hundred_chapters", "Сотня", "Прочитайте 100 глав", "star", "chapters", 100),
    Achievement("five_hundred_chapters", "Марафонец", "Прочитайте 500 глав", "sparkles", "chapters", 500),
    Achievement("first_title", "Первый тайтл", "Откройте первый тайтл", "compass", "titles", 1),
    Achievement("ten_titles", "Коллекционер", "Откройте 10 разных тайтлов", "grid", "titles", 10),
    Achievement("fifty_titles", "Библиотекарь", "Откройте 50 разных тайтлов", "list", "titles", 50),
    Achievement("first_finish", "До конца", "Завершите первый тайтл", "check", "finished", 1),
    Achievement("ten_finishes", "Завершитель", "Завершите 10 тайтлов", "check", "finished", 10),
    Achievement("first_day", "Первый день", "Заходите читать в течение дня", "clock", "days", 1),
    Achievement("week_streak", "Неделя с мангой", "Читайте 7 дней подряд", "heart", "streak", 7),
    Achievement("month_streak", "Месяц с мангой", "Читайте 30 дней подряд", "heart", "streak", 30),
    Achievement("level_5", "Уровень 5", "Достигните 5 уровня", "sparkles", "level", 5),
    Achievement("level_10", "Уровень 10", "Достигните 10 уровня", "sparkles", "level", 10),
    Achievement("level_25", "Уровень 25", "Достигните 25 уровня", "star", "level", 25),
)
ACHIEVEMENTS_BY_CODE = {item.code: item for item in ACHIEVEMENTS}


@dataclass(frozen=True, slots=True)
class ActivitySnapshot:
    chapters_read: int = 0
    titles_read: int = 0
    finished_titles: int = 0
    reading_days: int = 0
    current_streak: int = 0
    longest_streak: int = 0
    level: int = 1


def achievement_progress(achievement: Achievement, snapshot: ActivitySnapshot) -> int:
    value = {
        "chapters": snapshot.chapters_read,
        "titles": snapshot.titles_read,
        "finished": snapshot.finished_titles,
        "days": snapshot.reading_days,
        "streak": snapshot.longest_streak,
        "level": snapshot.level,
    }.get(achievement.metric, 0)
    return max(0, min(int(value), achievement.target))


def newly_unlocked(snapshot: ActivitySnapshot) -> list[Achievement]:
    return [
        achievement
        for achievement in ACHIEVEMENTS
        if achievement_progress(achievement, snapshot) >= achievement.target
    ]


@dataclass(slots=True)
class ProgressActivity:
    """Trusted catalogue metadata attached by the gateway to a progress save.

    The public client cannot set these fields directly: the gateway overwrites
    them from the catalogue before forwarding the internal request.
    """

    manga_id: uuid.UUID
    chapter_id: uuid.UUID
    manga_title: str = ""
    chapter_label: str = ""
    poster_url: str | None = None
    genres: list[str] = field(default_factory=list)
    title_completed: bool = False


@dataclass(slots=True)
class ActivityResult:
    xp_awarded: int = 0
    unlocked: list[str] = field(default_factory=list)


async def record_progress_activity(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    activity: ProgressActivity,
    now: datetime | None = None,
) -> ActivityResult:
    """Award XP/events/achievements for one progress save, idempotently.

    Must run in the same transaction as the progress upsert and reading-day
    record so a failed commit cannot leave profiling rows behind.
    """

    moment = as_utc(now) or datetime.now(UTC)
    result = ActivityResult()

    # One small bonus per UTC day.  The unique day key makes this idempotent
    # across devices and repeated chapter opens.
    if await add_xp_event(
        session,
        user_id=user_id,
        source="day",
        dedupe_key=utc_day_key(moment),
        xp=DAY_XP,
        created_at=moment,
    ):
        result.xp_awarded += DAY_XP

    # One event and one XP entry per chapter.  Re-opening a chapter never
    # awards again; deleting progress does not clear the ledger either.
    created = await add_profile_event(
        session,
        user_id=user_id,
        kind="chapter_read",
        dedupe_key=chapter_key(activity.chapter_id),
        manga_id=activity.manga_id,
        chapter_id=activity.chapter_id,
        manga_title=activity.manga_title,
        chapter_label=activity.chapter_label,
        poster_url=activity.poster_url,
        genres=activity.genres,
        created_at=moment,
    )
    if created:
        used = await chapter_xp_since(session, user_id, today_start(moment))
        award = max(0, min(CHAPTER_XP, CHAPTER_DAILY_CAP - used))
        await add_xp_event(
            session,
            user_id=user_id,
            source="chapter",
            dedupe_key=chapter_key(activity.chapter_id),
            xp=award,
            manga_id=activity.manga_id,
            chapter_id=activity.chapter_id,
            created_at=moment,
        )
        result.xp_awarded += award

    if activity.title_completed and await add_profile_event(
        session,
        user_id=user_id,
        kind="title_finished",
        dedupe_key=finish_key(activity.manga_id),
        manga_id=activity.manga_id,
        chapter_id=activity.chapter_id,
        manga_title=activity.manga_title,
        chapter_label=activity.chapter_label,
        poster_url=activity.poster_url,
        genres=activity.genres,
        created_at=moment,
    ):
        await add_xp_event(
            session,
            user_id=user_id,
            source="finish",
            dedupe_key=finish_key(activity.manga_id),
            xp=FINISH_XP,
            manga_id=activity.manga_id,
            chapter_id=activity.chapter_id,
            created_at=moment,
        )
        result.xp_awarded += FINISH_XP

    unlocked = await unlock_new_achievements(session, user_id=user_id, now=moment)
    result.unlocked = [item.code for item in unlocked]
    return result


async def activity_snapshot(
    session: AsyncSession, user_id: uuid.UUID, *, now: datetime
) -> ActivitySnapshot:
    days = await list_reading_days(session, user_id)
    streak = compute_streak([row.last_read_at for row in days], timezone="UTC", now=now)
    xp = await get_xp_total(session, user_id)
    return ActivitySnapshot(
        chapters_read=await count_profile_events(session, user_id, "chapter_read"),
        titles_read=await count_distinct_titles(session, user_id),
        finished_titles=await count_profile_events(session, user_id, "title_finished"),
        reading_days=await count_reading_days(session, user_id),
        current_streak=streak.current,
        longest_streak=streak.longest,
        level=level_for_xp(xp),
    )


async def unlock_new_achievements(
    session: AsyncSession, *, user_id: uuid.UUID, now: datetime
) -> list[Achievement]:
    snapshot = await activity_snapshot(session, user_id, now=now)
    already = await list_unlocked_achievements(session, user_id)
    unlocked: list[Achievement] = []
    for achievement in newly_unlocked(snapshot):
        if achievement.code in already:
            continue
        if await _unlock(session, user_id, achievement.code, now):
            await add_profile_event(
                session,
                user_id=user_id,
                kind="achievement",
                dedupe_key=achievement_key(achievement.code),
                achievement_code=achievement.code,
                created_at=now,
            )
            unlocked.append(achievement)
    return unlocked


async def _unlock(
    session: AsyncSession, user_id: uuid.UUID, code: str, now: datetime
) -> bool:
    from .profile_repository import unlock_achievement

    return await unlock_achievement(session, user_id=user_id, code=code, unlocked_at=now)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def profile_sections_visible(profile: UserProfile) -> bool:
    """Owner decision: any hidden public section makes the card guest-hidden.

    The safer interpretation is used: instead of exposing a partial card, the
    profile returns the same 404 as a private profile.  Owners still see their
    own page and can re-enable sections at any time.
    """

    return profile.show_stats and profile.show_events and profile.show_achievements


def profile_indexable(profile: UserProfile) -> bool:
    return bool(
        profile.indexable
        and not profile.is_private
        and profile_sections_visible(profile)
    )


def normalize_display_name(value: str) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    if not text:
        raise ValidationError("Имя не может быть пустым", code="invalid_display_name")
    if len(text) > 48:
        raise ValidationError("Имя длиннее 48 символов", code="invalid_display_name")
    if _CONTROL.search(text) or "<" in text or ">" in text:
        raise ValidationError("Имя содержит недопустимые символы", code="invalid_display_name")
    return text


def normalize_bio(value: str) -> str:
    text = (value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) > 280:
        raise ValidationError("Био длиннее 280 символов", code="invalid_bio")
    if _CONTROL.search(text) or "<" in text or ">" in text:
        raise ValidationError("Био содержит недопустимые символы", code="invalid_bio")
    return text


def normalize_report_reason(value: str) -> str:
    text = (value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text) < 3:
        raise ValidationError("Опишите причину жалобы", code="invalid_report_reason")
    if len(text) > 500:
        raise ValidationError("Причина длиннее 500 символов", code="invalid_report_reason")
    if _CONTROL.search(text) or "<" in text or ">" in text:
        raise ValidationError("Причина содержит недопустимые символы", code="invalid_report_reason")
    return text


def normalize_username(value: str) -> str:
    text = (value or "").strip().lower()
    if not USERNAME_PATTERN.fullmatch(text):
        raise ValidationError(
            "Ник: 3–24 символа, только латиница, цифры и «_»", code="invalid_username"
        )
    if text in RESERVED_USERNAMES:
        raise ValidationError("Этот ник зарезервирован", code="username_reserved")
    return text


def profile_not_found() -> NotFoundError:
    """Same 404 for missing, private, hidden and blocked profiles."""

    return NotFoundError(
        "Профиль не найден",
        code="profile_not_found",
        headers={"Cache-Control": "no-store"},
    )


def initials_for(display_name: str) -> str:
    parts = [part for part in re.split(r"\s+", display_name.strip()) if part]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][:1] + parts[1][:1]).upper()


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ProfileService:
    def __init__(
        self,
        settings: LibrarySettings,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory

    async def _resolve(
        self, session: AsyncSession, handle: str
    ) -> tuple[User, UserProfile] | None:
        value = (handle or "").strip()
        if not value:
            return None
        user: User | None = None
        try:
            user = await get_user(session, uuid.UUID(value))
        except ValueError:
            user = await get_user_by_username(session, value.lower())
        if user is None or not user.is_active:
            return None
        profile = await ensure_user_profile(session, user)
        return user, profile

    async def public_profile(
        self,
        handle: str,
        *,
        viewer_id: uuid.UUID | None = None,
        timezone: str | None = None,
    ) -> PublicProfileOut:
        async with self.session_factory() as session:
            resolved = await self._resolve(session, handle)
            if resolved is None:
                raise profile_not_found()
            user, profile = resolved
            owner = viewer_id is not None and viewer_id == user.id
            if not owner and viewer_id is not None and await is_blocked(session, viewer_id, user.id):
                raise profile_not_found()
            if not owner and (profile.is_private or not profile_sections_visible(profile)):
                raise profile_not_found()
            result = await self._build(
                session, user, profile, owner=owner, timezone=timezone, public=True
            )
            await session.commit()
            return result

    async def my_profile(
        self, user_id: uuid.UUID, *, timezone: str | None = None
    ) -> MyProfileOut:
        async with self.session_factory() as session:
            user = await get_user(session, user_id)
            if user is None or not user.is_active:
                raise NotFoundError("Профиль не найден", code="profile_not_found")
            profile = await ensure_user_profile(session, user)
            result = await self._build(
                session, user, profile, owner=True, timezone=timezone, public=False
            )
            await session.commit()
            return MyProfileOut.model_validate(result.model_dump())

    async def update_profile(
        self, user_id: uuid.UUID, payload: ProfileUpdate
    ) -> MyProfileOut:
        async with self.session_factory() as session:
            user = await get_user(session, user_id)
            if user is None or not user.is_active:
                raise NotFoundError("Профиль не найден", code="profile_not_found")
            profile = await ensure_user_profile(session, user)
            fields = payload.model_fields_set
            values: dict[str, object] = {}

            if "display_name" in fields and payload.display_name is not None:
                display_name = normalize_display_name(payload.display_name)
                user.display_name = display_name
            if "username" in fields and payload.username is not None:
                username = normalize_username(payload.username)
                if await username_taken(session, username, exclude_user_id=user.id):
                    raise ConflictError("Этот ник уже занят", code="username_taken")
                values["username"] = username
            if "bio" in fields and payload.bio is not None:
                values["bio"] = normalize_bio(payload.bio)
            for flag in ("is_private", "show_stats", "show_events", "show_achievements", "indexable"):
                if flag in fields:
                    values[flag] = bool(getattr(payload, flag))
            if values:
                await update_profile_fields(session, profile, values)
            await session.flush()
            result = await self._build(
                session, user, profile, owner=True, timezone=None, public=False
            )
            await session.commit()
            return MyProfileOut.model_validate(result.model_dump())

    async def report(
        self, reporter_id: uuid.UUID, handle: str, reason: str
    ) -> ProfileReportOut:
        text = normalize_report_reason(reason)
        async with self.session_factory() as session:
            resolved = await self._resolve(session, handle)
            if resolved is None:
                raise NotFoundError("Профиль не найден", code="profile_not_found")
            user, _ = resolved
            if user.id == reporter_id:
                raise ValidationError("Нельзя пожаловаться на себя", code="self_report")
            report = await find_open_report(session, reporter_id, user.id)
            if report is None:
                report = await create_report(
                    session,
                    reporter_id=reporter_id,
                    target_user_id=user.id,
                    reason=text,
                )
                logger.info("profile report created", extra={"target_user_id": str(user.id)})
            await session.commit()
            return ProfileReportOut(id=report.id, status=report.status, created_at=report.created_at)

    async def block(
        self, blocker_id: uuid.UUID, handle: str, *, blocked: bool
    ) -> OkResponse:
        async with self.session_factory() as session:
            resolved = await self._resolve(session, handle)
            if resolved is None:
                raise NotFoundError("Профиль не найден", code="profile_not_found")
            user, _ = resolved
            if user.id == blocker_id:
                raise ValidationError("Нельзя заблокировать себя", code="self_block")
            await set_block(session, blocker_id, user.id, blocked)
            await session.commit()
            return OkResponse(
                message="Пользователь заблокирован" if blocked else "Пользователь разблокирован"
            )

    async def list_reports(
        self, *, status: str = "open", limit: int = 50
    ) -> list[AdminProfileReportOut]:
        async with self.session_factory() as session:
            reports = await list_reports(session, status=status, limit=limit)
            result: list[AdminProfileReportOut] = []
            for report in reports:
                target = await get_user(session, report.target_user_id)
                reporter = await get_user(session, report.reporter_id)
                target_profile = (
                    await get_profile(session, report.target_user_id) if target else None
                )
                reporter_profile = (
                    await get_profile(session, report.reporter_id) if reporter else None
                )
                result.append(
                    AdminProfileReportOut(
                        id=report.id,
                        target_username=(target_profile.username if target_profile else None)
                        or (str(target.id) if target else "unknown"),
                        target_display_name=target.display_name if target else "Удалённый профиль",
                        reporter_username=(reporter_profile.username if reporter_profile else None)
                        or (str(reporter.id) if reporter else "unknown"),
                        reason=report.reason,
                        status=report.status,
                        target_visible=bool(
                            target_profile
                            and not target_profile.is_private
                            and profile_sections_visible(target_profile)
                        ),
                        created_at=report.created_at,
                        resolved_at=report.resolved_at,
                    )
                )
            return result

    async def resolve_report(
        self, report_id: uuid.UUID, status: str
    ) -> AdminProfileReportOut:
        async with self.session_factory() as session:
            report = await get_report(session, report_id)
            if report is None:
                raise NotFoundError("Жалоба не найдена", code="report_not_found")
            if status not in {"resolved", "dismissed"}:
                raise ValidationError("Неизвестный статус", code="invalid_status")
            target = await get_user(session, report.target_user_id)
            reporter = await get_user(session, report.reporter_id)
            target_profile = await get_profile(session, report.target_user_id) if target else None
            reporter_profile = await get_profile(session, report.reporter_id) if reporter else None
            await resolve_report(session, report, status)
            await session.commit()
            return AdminProfileReportOut(
                id=report.id,
                target_username=(target_profile.username if target_profile else None)
                or (str(target.id) if target else "unknown"),
                target_display_name=target.display_name if target else "Удалённый профиль",
                reporter_username=(reporter_profile.username if reporter_profile else None)
                or (str(reporter.id) if reporter else "unknown"),
                reason=report.reason,
                status=report.status,
                target_visible=bool(
                    target_profile
                    and not target_profile.is_private
                    and profile_sections_visible(target_profile)
                ),
                created_at=report.created_at,
                resolved_at=report.resolved_at,
            )

    async def my_events(
        self, user_id: uuid.UUID, limit: int = 30
    ) -> list[ProfileEventOut]:
        async with self.session_factory() as session:
            rows = await list_profile_events(session, user_id, limit=max(1, min(limit, 100)))
            return [self._event_out(row, owner=True) for row in rows]

    async def _build(
        self,
        session: AsyncSession,
        user: User,
        profile: UserProfile,
        *,
        owner: bool,
        timezone: str | None,
        public: bool,
    ) -> PublicProfileOut:
        xp = await get_xp_total(session, user.id)
        level = level_for_xp(xp)
        rank = rank_for_level(level)
        next_rank = next_rank_for_level(level)
        into_level = xp - xp_for_level(level)
        for_next = max(1, xp_for_level(min(level + 1, MAX_LEVEL)) - xp_for_level(level))
        if level >= MAX_LEVEL:
            into_level = 0
            for_next = 0

        show_stats = owner or profile.show_stats
        show_events = owner or profile.show_events
        show_achievements = owner or profile.show_achievements
        # Level and rank are the public identity of the card.  Exact XP and
        # progress are aggregate stats, so they disappear with the stats block.
        public_xp = xp if show_stats else 0
        public_into_level = into_level if show_stats else 0
        public_for_next = for_next if show_stats else 0

        stats: ProfileStatsOut | None = None
        genres: list[GenreCountOut] = []
        if show_stats:
            days = await list_reading_days(session, user.id)
            streak = compute_streak(
                [row.last_read_at for row in days],
                timezone=timezone if owner else "UTC",
                now=datetime.now(UTC),
            )
            stats = ProfileStatsOut(
                chapters_read=await count_profile_events(session, user.id, "chapter_read"),
                titles_read=await count_distinct_titles(session, user.id),
                finished_titles=await count_profile_events(session, user.id, "title_finished"),
                reading_days=await count_reading_days(session, user.id),
                current_streak=streak.current,
                longest_streak=streak.longest,
            )
            genres = [
                GenreCountOut(genre=name, count=count)
                for name, count in await favorite_genres(session, user.id)
            ]

        unlocked = await list_unlocked_achievements(session, user.id) if show_achievements else {}
        if show_achievements:
            snapshot = await activity_snapshot(session, user.id, now=datetime.now(UTC))
            achievements = [
                AchievementOut(
                    code=item.code,
                    title=item.title,
                    description=item.description,
                    icon=item.icon,
                    unlocked=item.code in unlocked,
                    unlocked_at=as_utc(unlocked.get(item.code)) if owner else None,
                    unlocked_on=as_date(unlocked.get(item.code)) if item.code in unlocked else None,
                    progress=achievement_progress(item, snapshot),
                    target=item.target,
                )
                for item in ACHIEVEMENTS
            ]
            if public and not owner:
                achievements = [item for item in achievements if item.unlocked]
        else:
            achievements = []

        events: list[ProfileEventOut] = []
        if show_events:
            rows = await list_profile_events(session, user.id, limit=30)
            events = [self._event_out(row, owner=owner) for row in rows]

        return PublicProfileOut(
            # Never fall back to the internal user id: it must not leak into a
            # public response even if a profile row is incomplete.
            username=profile.username or "reader",
            display_name=user.display_name,
            bio=profile.bio or "",
            joined_at=as_date(user.created_at),
            level=level,
            xp=public_xp,
            xp_into_level=public_into_level,
            xp_for_next_level=public_for_next,
            level_progress=(
                round(public_into_level / public_for_next, 4) if public_for_next else 0.0
            ),
            rank=RankOut(code=rank.code, label=rank.label, min_level=rank.min_level),
            next_rank=(
                RankOut(code=next_rank.code, label=next_rank.label, min_level=next_rank.min_level)
                if next_rank
                else None
            ),
            avatar_initials=initials_for(user.display_name),
            privacy=ProfilePrivacyOut(
                is_private=profile.is_private,
                show_stats=profile.show_stats,
                show_events=profile.show_events,
                show_achievements=profile.show_achievements,
                indexable=profile.indexable,
            ),
            indexable=profile_indexable(profile),
            is_owner=owner,
            stats=stats,
            favorite_genres=genres,
            achievements=achievements,
            achievements_unlocked=len(unlocked) if show_achievements else 0,
            achievements_total=len(ACHIEVEMENTS) if show_achievements else 0,
            achievements_hidden=not show_achievements,
            events=events,
            events_hidden=not show_events,
        )

    @staticmethod
    def _event_out(row: ProfileEvent, *, owner: bool) -> ProfileEventOut:
        title = row.manga_title or "Тайтл"
        subtitle = row.chapter_label
        if row.kind == "title_finished":
            title = f"Завершён тайтл: {row.manga_title or 'без названия'}"
            subtitle = row.chapter_label
        elif row.kind == "achievement":
            achievement = ACHIEVEMENTS_BY_CODE.get(row.achievement_code or "")
            title = f"Достижение: {achievement.title if achievement else 'новое'}"
            subtitle = achievement.description if achievement else None
        moment = as_utc(row.created_at)
        return ProfileEventOut(
            id=row.id,
            kind=row.kind,  # type: ignore[arg-type]
            title=title,
            subtitle=subtitle,
            manga_id=row.manga_id,
            chapter_id=row.chapter_id,
            poster_url=row.poster_url,
            achievement_code=row.achievement_code,
            occurred_on=as_date(moment),
            created_at=moment if owner else None,
        )
