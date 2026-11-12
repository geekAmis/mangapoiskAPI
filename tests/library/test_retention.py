from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from manga_common.db import create_all, create_engine, create_session_factory
from manga_common.schemas import AnalyticsEventIn
from services.library.app.analytics import compute_retention
from services.library.app.config import LibrarySettings
from services.library.app.models import AnalyticsEvent
from services.library.app.repository import insert_analytics_events
from services.library.app.service import LibraryService
from services.library.app.streak import compute_streak


async def make_service(tmp_path: Path) -> tuple[LibraryService, object, uuid.UUID]:
    db_path = tmp_path / "retention.db"
    settings = LibrarySettings(
        service_name="library-retention-test",
        library_database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
        jwt_secret="library-retention-test-secret",
    )
    engine = create_engine(settings.library_dsn)
    session_factory = create_session_factory(engine)
    await create_all(engine)
    service = LibraryService(settings, session_factory)
    tokens = await service.register(
        email="retention@example.com",
        password="very-secret-password",
        display_name="Retention",
    )
    return service, engine, tokens.user.id


@pytest.mark.asyncio
async def test_merge_local_progress_keeps_newest_without_duplicates(tmp_path: Path) -> None:
    service, engine, user_id = await make_service(tmp_path)
    manga_a = uuid.uuid4()
    manga_b = uuid.uuid4()
    chapter_a = uuid.uuid4()
    chapter_b = uuid.uuid4()
    now = datetime.now(UTC)

    await service.upsert_progress(
        user_id, manga_id=manga_a, chapter_id=chapter_a, page=3, total_pages=20
    )

    from manga_common.schemas import ProgressMergeItem

    # A future-ish device clock is clamped and wins over the account copy.
    # Same manga twice: only the newest local position may win, and the older
    # duplicate must not create a second row.
    result = await service.merge_local_progress(
        user_id,
        [
            ProgressMergeItem(
                manga_id=manga_a,
                chapter_id=chapter_a,
                page=8,
                total_pages=20,
                read_at=now + timedelta(hours=1),
            ),
            ProgressMergeItem(
                manga_id=manga_b,
                chapter_id=chapter_b,
                page=4,
                total_pages=10,
                read_at=now - timedelta(hours=1),
            ),
            ProgressMergeItem(
                manga_id=manga_b,
                chapter_id=chapter_b,
                page=2,
                total_pages=10,
                read_at=now - timedelta(hours=2),
            ),
        ],
        read_days=[now - timedelta(days=2), now - timedelta(days=1)],
    )
    assert result.merged == 2
    assert result.ignored == 1
    # The local streak history follows the account on sign-in.
    streak = await service.streak(user_id, "UTC")
    assert streak.current == 3
    assert streak.longest == 3

    history = await service.history(user_id)
    assert len(history) == 2
    assert history[0].manga_id == manga_a
    assert history[0].page == 8
    assert history[1].manga_id == manga_b
    assert history[1].page == 4

    # A stale offline device cannot rewind an account position.
    stale = await service.merge_local_progress(
        user_id,
        [
            ProgressMergeItem(
                manga_id=manga_a,
                chapter_id=chapter_a,
                page=1,
                total_pages=20,
                read_at=now - timedelta(days=2),
            )
        ],
    )
    assert stale.unchanged == 1
    history = await service.history(user_id)
    assert next(item for item in history if item.manga_id == manga_a).page == 8

    # Repeating the same merge is idempotent.
    repeated = await service.merge_local_progress(
        user_id,
        [
            ProgressMergeItem(
                manga_id=manga_b,
                chapter_id=chapter_b,
                page=4,
                total_pages=10,
                read_at=now - timedelta(hours=1),
            )
        ],
    )
    assert repeated.merged == 0
    assert len(await service.history(user_id)) == 2

    await engine.dispose()


def test_streak_is_timezone_aware_and_forgiving() -> None:
    now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)  # 15:00 Moscow
    timestamps = [
        datetime(2026, 5, 8, 10, 0, tzinfo=UTC),
        datetime(2026, 5, 9, 10, 0, tzinfo=UTC),
        datetime(2026, 5, 10, 10, 0, tzinfo=UTC),
    ]
    streak = compute_streak(timestamps, timezone="Europe/Moscow", now=now)
    assert streak.current == 3
    assert streak.longest == 3
    assert streak.read_today is True
    assert streak.days[-1] == "2026-05-10"

    # Not reading yet today keeps yesterday's streak alive; nothing is reset
    # mid-day and no "punishment" state is exposed.
    grace = compute_streak(timestamps[:2], timezone="Europe/Moscow", now=now)
    assert grace.current == 2
    assert grace.read_today is False

    gap = compute_streak(
        [datetime(2026, 5, 5, 10, 0, tzinfo=UTC), timestamps[0]],
        timezone="Europe/Moscow",
        now=now,
    )
    assert gap.current == 0
    assert gap.longest == 1

    # Crossing the UTC date boundary must count two local Tokyo days.
    tokyo_now = datetime(2026, 1, 2, 0, 30, tzinfo=UTC)  # Jan 2 09:30 in Tokyo
    tokyo = compute_streak(
        [
            datetime(2026, 1, 1, 14, 0, tzinfo=UTC),  # Jan 1 23:00 local
            datetime(2026, 1, 1, 15, 0, tzinfo=UTC),  # Jan 2 00:00 local
        ],
        timezone="Asia/Tokyo",
        now=tokyo_now,
    )
    assert tokyo.current == 2

    # DST transition is just another local calendar day.
    dst = compute_streak(
        [
            datetime(2026, 3, 7, 12, 0, tzinfo=UTC),
            datetime(2026, 3, 8, 12, 0, tzinfo=UTC),
            datetime(2026, 3, 9, 12, 0, tzinfo=UTC),
        ],
        timezone="America/New_York",
        now=datetime(2026, 3, 9, 23, 0, tzinfo=UTC),
    )
    assert dst.current == 3

    fallback = compute_streak(timestamps, timezone="Mars/Olympus", now=now)
    assert fallback.timezone == "UTC"
    assert fallback.current == 3

    empty = compute_streak([], timezone="Europe/Moscow", now=now)
    assert empty.current == 0
    assert empty.longest == 0


@pytest.mark.asyncio
async def test_analytics_ingest_is_idempotent(tmp_path: Path) -> None:
    service, engine, _ = await make_service(tmp_path)
    event = AnalyticsEventIn(
        event="read_start",
        dedupe_key="device-1:chapter-1:start",
        client_id="device-1",
        surface="reader",
        manga_id=uuid.uuid4(),
        chapter_id=uuid.uuid4(),
    )
    first = await service.ingest_analytics([event])
    second = await service.ingest_analytics([event])
    assert first.accepted == 1
    assert first.duplicates == 0
    assert second.accepted == 0
    assert second.duplicates == 1

    async with service.session_factory() as session:
        from sqlalchemy import func, select

        count = await session.scalar(select(func.count(AnalyticsEvent.id)))
        assert count == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_retention_query_builds_weekly_cohorts(tmp_path: Path) -> None:
    service, engine, _ = await make_service(tmp_path)
    now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
    rows = [
        # Cohort week 2026-04-27: two clients.
        {
            "event": "read_start",
            "client_id": "a",
            "surface": "reader",
            "dedupe_key": "a-1",
            "created_at": datetime(2026, 5, 1, 10, 0, tzinfo=UTC),
        },
        {
            "event": "read_complete",
            "client_id": "a",
            "surface": "reader",
            "dedupe_key": "a-2",
            "created_at": datetime(2026, 5, 2, 10, 0, tzinfo=UTC),
        },
        {
            "event": "read_start",
            "client_id": "a",
            "surface": "reader",
            "dedupe_key": "a-3",
            "created_at": datetime(2026, 5, 8, 10, 0, tzinfo=UTC),
        },
        {
            "event": "read_start",
            "client_id": "b",
            "surface": "home",
            "dedupe_key": "b-1",
            "created_at": datetime(2026, 5, 1, 11, 0, tzinfo=UTC),
        },
        {
            "event": "click",
            "client_id": "b",
            "surface": "home",
            "dedupe_key": "b-2",
            "created_at": datetime(2026, 5, 2, 11, 0, tzinfo=UTC),
        },
        # Cohort week 2026-05-04: one client, no D1 return.
        {
            "event": "read_start",
            "client_id": "c",
            "surface": "reader",
            "dedupe_key": "c-1",
            "created_at": datetime(2026, 5, 4, 9, 0, tzinfo=UTC),
        },
    ]
    async with service.session_factory() as session:
        accepted, duplicates = await insert_analytics_events(session, rows)
        await session.commit()
        assert accepted == 6
        assert duplicates == 0
        from sqlalchemy import select

        events = list((await session.scalars(select(AnalyticsEvent))).all())

    retention = compute_retention(events, days=30, now=now)
    by_cohort = {cohort.cohort: cohort for cohort in retention.cohorts}
    first = by_cohort["2026-04-27"]
    assert first.size == 2
    assert first.d1 == 2
    assert first.d7 == 1
    assert first.d7_rate == 0.5
    second = by_cohort["2026-05-04"]
    assert second.size == 1
    assert second.d1 == 0
    await engine.dispose()
