from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from manga_common.db import create_all, create_engine, create_session_factory
from manga_common.errors import ConflictError, NotFoundError, ValidationError
from manga_common.profile_schemas import ProfileUpdate
from services.library.app.config import LibrarySettings
from services.library.app.profile_repository import (
    get_xp_total,
    list_profile_events,
    list_unlocked_achievements,
)
from services.library.app.profiles import (
    ACHIEVEMENTS,
    ACHIEVEMENTS_BY_CODE,
    CHAPTER_DAILY_CAP,
    CHAPTER_XP,
    DAY_XP,
    FINISH_XP,
    ProfileService,
    ProgressActivity,
    initials_for,
    level_for_xp,
    normalize_bio,
    normalize_display_name,
    normalize_username,
    rank_for_level,
    record_progress_activity,
    xp_for_level,
)
from services.library.app.repository import record_reading_day
from services.library.app.service import LibraryService


async def make_stack(tmp_path: Path) -> tuple[LibraryService, ProfileService, object]:
    db_path = tmp_path / "profiles.db"
    settings = LibrarySettings(
        service_name="library-profile-test",
        library_database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
        jwt_secret="library-profile-test-secret",
    )
    engine = create_engine(settings.library_dsn)
    session_factory = create_session_factory(engine)
    await create_all(engine)
    return (
        LibraryService(settings, session_factory),
        ProfileService(settings, session_factory),
        engine,
    )


async def register(service: LibraryService, email: str, name: str) -> uuid.UUID:
    tokens = await service.register(
        email=email, password="very-secret-password", display_name=name
    )
    return tokens.user.id


async def add_activity(
    service: LibraryService,
    user_id: uuid.UUID,
    *,
    now: datetime,
    manga_id: uuid.UUID | None = None,
    chapter_id: uuid.UUID | None = None,
    title: str = "Тестовый тайтл",
    genres: list[str] | None = None,
    completed: bool = False,
) -> None:
    manga_id = manga_id or uuid.uuid4()
    chapter_id = chapter_id or uuid.uuid4()
    async with service.session_factory() as session:
        await record_reading_day(session, user_id=user_id, read_at=now)
        await record_progress_activity(
            session,
            user_id=user_id,
            activity=ProgressActivity(
                manga_id=manga_id,
                chapter_id=chapter_id,
                manga_title=title,
                chapter_label="Глава 1",
                poster_url="https://example.test/poster.jpg",
                genres=genres or ["Экшен", "Фэнтези"],
                title_completed=completed,
            ),
            now=now,
        )
        await session.commit()


async def xp(service: LibraryService, user_id: uuid.UUID) -> int:
    async with service.session_factory() as session:
        return await get_xp_total(session, user_id)


async def _unlocked(service: LibraryService, user_id: uuid.UUID) -> set[str]:
    async with service.session_factory() as session:
        return set((await list_unlocked_achievements(session, user_id)).keys())


def _all_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        keys.update(value)
        for item in value.values():
            keys.update(_all_keys(item))
    elif isinstance(value, list):
        for item in value:
            keys.update(_all_keys(item))
    return keys


def test_level_thresholds_are_deterministic() -> None:
    assert xp_for_level(1) == 0
    assert xp_for_level(2) == 50
    assert xp_for_level(3) == 150
    assert xp_for_level(10) == 2250
    assert [level_for_xp(value) for value in (0, 49, 50, 149, 150, 299, 300, 2250)] == [
        1,
        1,
        2,
        2,
        3,
        3,
        4,
        10,
    ]
    assert level_for_xp(10**9) == 99


def test_rank_bands_and_validation() -> None:
    assert rank_for_level(1).code == "reader"
    assert rank_for_level(2).code == "reader"
    assert rank_for_level(3).code == "regular"
    assert rank_for_level(5).code == "enthusiast"
    assert rank_for_level(8).code == "senpai"
    assert rank_for_level(12).code == "sensei"
    assert rank_for_level(17).code == "storyteller"
    assert rank_for_level(25).code == "legend"
    assert rank_for_level(99).code == "legend"

    assert normalize_display_name("  Иван   Петров  ") == "Иван Петров"
    assert normalize_username("Manga_Fan") == "manga_fan"
    assert normalize_bio("  строка\r\n\r\n\r\nвторая  ") == "строка\n\nвторая"
    assert initials_for("Иван Петров") == "ИП"
    assert initials_for("Читатель") == "ЧИ"

    with pytest.raises(ValidationError):
        normalize_display_name("   ")
    with pytest.raises(ValidationError):
        normalize_display_name("<script>")
    with pytest.raises(ValidationError):
        normalize_username("ab")
    with pytest.raises(ValidationError):
        normalize_username("admin")
    with pytest.raises(ValidationError):
        normalize_bio("x" * 281)


@pytest.mark.asyncio
async def test_xp_is_idempotent_and_daily_cap_applies(tmp_path: Path) -> None:
    service, _, engine = await make_stack(tmp_path)
    user_id = await register(service, "xp@example.com", "XP Reader")
    now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
    manga = uuid.uuid4()
    chapters = [uuid.uuid4() for _ in range(10)]

    await add_activity(service, user_id, now=now, manga_id=manga, chapter_id=chapters[0])
    assert await xp(service, user_id) == DAY_XP + CHAPTER_XP

    # Re-opening the same chapter on the same day is a no-op.
    await add_activity(service, user_id, now=now, manga_id=manga, chapter_id=chapters[0])
    assert await xp(service, user_id) == DAY_XP + CHAPTER_XP

    # Ten distinct chapters in one UTC day hit the 100 XP chapter cap.
    for chapter_id in chapters[1:]:
        await add_activity(service, user_id, now=now, manga_id=manga, chapter_id=chapter_id)
    assert await xp(service, user_id) == DAY_XP + CHAPTER_DAILY_CAP
    async with service.session_factory() as session:
        events = await list_profile_events(session, user_id, limit=100)
        assert len([item for item in events if item.kind == "chapter_read"]) == 10

    # A new UTC day grants the day bonus and chapter XP again.
    tomorrow = now + timedelta(days=1)
    await add_activity(service, user_id, now=tomorrow)
    assert await xp(service, user_id) == DAY_XP * 2 + CHAPTER_DAILY_CAP + CHAPTER_XP

    await engine.dispose()


@pytest.mark.asyncio
async def test_achievements_unlock_once_and_title_finish_is_idempotent(
    tmp_path: Path,
) -> None:
    service, profiles, engine = await make_stack(tmp_path)
    user_id = await register(service, "achieve@example.com", "Achiever")
    now = datetime(2026, 5, 10, 9, 0, tzinfo=UTC)
    manga = uuid.uuid4()
    chapters = [uuid.uuid4() for _ in range(10)]

    await add_activity(service, user_id, now=now, manga_id=manga, chapter_id=chapters[0])
    unlocked = await _unlocked(service, user_id)
    assert {"first_chapter", "first_title", "first_day"} <= unlocked

    for chapter_id in chapters[1:]:
        await add_activity(service, user_id, now=now, manga_id=manga, chapter_id=chapter_id)
    unlocked = await _unlocked(service, user_id)
    assert "ten_chapters" in unlocked

    before = await xp(service, user_id)
    await add_activity(service, user_id, now=now, manga_id=manga, chapter_id=chapters[0])
    assert await _unlocked(service, user_id) == unlocked
    assert await xp(service, user_id) == before

    # Finishing the title grants FINISH_XP and a single achievement.  The
    # chapter is already in the ledger, so no duplicate chapter event appears.
    await add_activity(
        service,
        user_id,
        now=now,
        manga_id=manga,
        chapter_id=chapters[0],
        completed=True,
    )
    assert await xp(service, user_id) == before + FINISH_XP
    assert "first_finish" in await _unlocked(service, user_id)
    await add_activity(
        service,
        user_id,
        now=now,
        manga_id=manga,
        chapter_id=chapters[0],
        completed=True,
    )
    assert await xp(service, user_id) == before + FINISH_XP
    async with service.session_factory() as session:
        events = await list_profile_events(session, user_id, limit=200)
        achievement_events = [item for item in events if item.kind == "achievement"]
        finish_events = [item for item in events if item.kind == "title_finished"]
        assert len(finish_events) == 1
        assert len(achievement_events) == len(
            {item.achievement_code for item in achievement_events}
        )

    my = await profiles.my_profile(user_id)
    assert my.level >= 2
    assert my.stats is not None
    assert my.stats.titles_read == 1
    assert my.stats.finished_titles == 1
    assert my.stats.chapters_read == 10
    assert my.favorite_genres

    await engine.dispose()


@pytest.mark.asyncio
async def test_streak_achievement_uses_existing_reading_days(tmp_path: Path) -> None:
    service, profiles, engine = await make_stack(tmp_path)
    user_id = await register(service, "streak@example.com", "Streaker")
    now = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
    for offset in range(7):
        await add_activity(service, user_id, now=now - timedelta(days=6 - offset))
    assert "week_streak" in await _unlocked(service, user_id)
    my = await profiles.my_profile(user_id, timezone="Europe/Moscow")
    assert my.stats is not None
    assert my.stats.current_streak == 7
    assert my.stats.longest_streak == 7
    await engine.dispose()


@pytest.mark.asyncio
async def test_public_profile_is_indexable_by_default_and_no_pii_leaks(
    tmp_path: Path,
) -> None:
    service, profiles, engine = await make_stack(tmp_path)
    user_id = await register(service, "privacy@example.com", "Private Reader")
    now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
    await add_activity(service, user_id, now=now, genres=["Драма"])

    my = await profiles.my_profile(user_id)
    assert my.is_owner is True
    assert my.stats is not None
    assert my.events and not my.events_hidden
    assert my.privacy.show_events is True
    assert my.privacy.indexable is True
    assert my.indexable is True
    assert my.username

    guest = await profiles.public_profile(my.username)
    assert guest.is_owner is False
    assert guest.events and guest.events_hidden is False
    assert guest.stats is not None
    assert guest.indexable is True
    assert guest.achievements
    assert all(item.unlocked for item in guest.achievements)

    # Public activity is date-only: exact reading/achievement timestamps are
    # reserved for the owner.
    assert guest.events[0].created_at is None
    assert isinstance(guest.events[0].occurred_on, date)
    for achievement in guest.achievements:
        assert achievement.unlocked_at is None
        assert achievement.unlocked_on is not None

    payload = guest.model_dump()
    keys = _all_keys(payload)
    for forbidden in (
        "email",
        "password_hash",
        "ip_address",
        "user_agent",
        "role",
        "user_id",
        "reporter_id",
        "refresh_token",
    ):
        assert forbidden not in keys

    # Owner decision: hiding any public section makes the card noindex and
    # guest-invisible.  The owner still sees their own profile.
    await profiles.update_profile(user_id, ProfileUpdate(show_stats=False))
    with pytest.raises(NotFoundError):
        await profiles.public_profile(my.username)
    owner = await profiles.my_profile(user_id)
    assert owner.stats is not None
    assert owner.indexable is False

    await profiles.update_profile(user_id, ProfileUpdate(show_stats=True, show_events=False))
    with pytest.raises(NotFoundError):
        await profiles.public_profile(my.username)
    assert (await profiles.my_profile(user_id)).events

    await profiles.update_profile(
        user_id, ProfileUpdate(show_events=True, show_achievements=False)
    )
    with pytest.raises(NotFoundError):
        await profiles.public_profile(my.username)

    await profiles.update_profile(
        user_id, ProfileUpdate(show_achievements=True, is_private=True)
    )
    with pytest.raises(NotFoundError):
        await profiles.public_profile(my.username)

    # Opting out of indexing alone keeps the card public but noindex.
    await profiles.update_profile(
        user_id, ProfileUpdate(is_private=False, indexable=False)
    )
    guest = await profiles.public_profile(my.username)
    assert guest.indexable is False

    await profiles.update_profile(user_id, ProfileUpdate(indexable=True))
    assert (await profiles.public_profile(my.username)).indexable is True
    await engine.dispose()


@pytest.mark.asyncio
async def test_reports_blocks_and_username_changes(tmp_path: Path) -> None:
    service, profiles, engine = await make_stack(tmp_path)
    alice = await register(service, "alice@example.com", "Alice")
    bob = await register(service, "bob@example.com", "Bob")
    await profiles.my_profile(alice)
    bob_profile = await profiles.my_profile(bob)

    report = await profiles.report(alice, bob_profile.username, "Оскорбительное био")
    duplicate = await profiles.report(alice, bob_profile.username, "Повтор")
    assert report.id == duplicate.id
    reports = await profiles.list_reports(status="open")
    assert len(reports) == 1
    assert reports[0].target_username == bob_profile.username
    assert reports[0].target_visible is True
    assert "email" not in reports[0].model_dump()
    resolved = await profiles.resolve_report(report.id, "resolved")
    assert resolved.status == "resolved"

    await profiles.update_profile(bob, ProfileUpdate(show_events=False))
    hidden_reports = await profiles.list_reports(status="all")
    assert hidden_reports[0].target_visible is False
    await profiles.update_profile(bob, ProfileUpdate(show_events=True))

    await profiles.block(alice, bob_profile.username, blocked=True)
    with pytest.raises(NotFoundError):
        await profiles.public_profile(bob_profile.username, viewer_id=alice)
    await profiles.block(alice, bob_profile.username, blocked=False)
    assert (
        await profiles.public_profile(bob_profile.username, viewer_id=alice)
    ).is_owner is False

    updated = await profiles.update_profile(
        alice,
        ProfileUpdate(username="alice_new", bio="Люблю мангу", display_name="Alice A"),
    )
    assert updated.username == "alice_new"
    assert updated.bio == "Люблю мангу"
    assert updated.display_name == "Alice A"

    with pytest.raises(ConflictError):
        await profiles.update_profile(alice, ProfileUpdate(username=bob_profile.username))
    with pytest.raises(ValidationError):
        await profiles.update_profile(alice, ProfileUpdate(username="admin"))
    with pytest.raises(ValidationError):
        await profiles.report(alice, updated.username, "сам на себя")
    with pytest.raises(ValidationError):
        await profiles.report(alice, bob_profile.username, "<script>")
    await engine.dispose()


@pytest.mark.asyncio
async def test_service_progress_path_awards_xp_and_rejects_duplicates(
    tmp_path: Path,
) -> None:
    service, profiles, engine = await make_stack(tmp_path)
    user_id = await register(service, "service@example.com", "Service Reader")
    manga = uuid.uuid4()
    chapter = uuid.uuid4()
    activity = ProgressActivity(
        manga_id=manga,
        chapter_id=chapter,
        manga_title="Сервисный тайтл",
        chapter_label="Глава 1",
        genres=["Романтика"],
    )
    await service.upsert_progress(
        user_id,
        manga_id=manga,
        chapter_id=chapter,
        page=1,
        total_pages=20,
        activity=activity,
    )
    await service.upsert_progress(
        user_id,
        manga_id=manga,
        chapter_id=chapter,
        page=10,
        total_pages=20,
        activity=activity,
    )
    my = await profiles.my_profile(user_id)
    assert my.stats is not None
    assert my.stats.chapters_read == 1
    assert my.xp == DAY_XP + CHAPTER_XP
    await engine.dispose()


def test_achievement_catalog_is_well_formed() -> None:
    codes = [item.code for item in ACHIEVEMENTS]
    assert len(codes) == len(set(codes))
    assert set(ACHIEVEMENTS_BY_CODE) == set(codes)
    for item in ACHIEVEMENTS:
        assert item.target > 0
        assert item.metric in {"chapters", "titles", "finished", "days", "streak", "level"}
