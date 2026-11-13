from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from manga_common.db import create_all, create_engine, create_session_factory
from services.library.app import service as service_module
from services.library.app.config import LibrarySettings
from services.library.app.repository import (
    record_traffic_visit as repository_record_traffic_visit,
)
from services.library.app.service import LibraryService
from sqlalchemy import text

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
VISITOR_A = "a" * 64
VISITOR_B = "b" * 64
VISITOR_C = "c" * 64


async def make_service(tmp_path: Path) -> tuple[LibraryService, object]:
    db_path = tmp_path / "traffic.db"
    settings = LibrarySettings(
        service_name="library-traffic-test",
        library_database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
        jwt_secret="library-traffic-test-secret",
        traffic_retention_days=90,
    )
    engine = create_engine(settings.library_dsn)
    await create_all(engine)
    return LibraryService(settings, create_session_factory(engine)), engine


@pytest.mark.asyncio
async def test_visit_is_deduplicated_per_visitor_and_day(tmp_path: Path) -> None:
    service, engine = await make_service(tmp_path)

    first = await service.record_traffic_visit(VISITOR_A, "home", now=NOW)
    second = await service.record_traffic_visit(VISITOR_A, "manga", now=NOW)
    next_day = await service.record_traffic_visit(
        VISITOR_A, "manga", now=NOW + timedelta(days=1)
    )

    assert first is True
    assert second is False
    assert next_day is True
    async with engine.connect() as connection:
        rows = (
            await connection.execute(
                text("SELECT visitor_hash, day, path_group FROM traffic_visits ORDER BY day")
            )
        ).fetchall()
    assert len(rows) == 2
    assert rows[0][0] == VISITOR_A
    assert rows[0][2] == "home"
    assert rows[1][2] == "manga"
    await engine.dispose()


@pytest.mark.asyncio
async def test_unique_counts_daily_series_and_goal(tmp_path: Path) -> None:
    service, engine = await make_service(tmp_path)

    await service.record_traffic_visit(VISITOR_A, "home", now=NOW - timedelta(days=6))
    await service.record_traffic_visit(VISITOR_A, "manga", now=NOW)
    await service.record_traffic_visit(VISITOR_B, "catalogue", now=NOW)
    # Outside the 30-day window and outside the 90-day table retention.
    await service.record_traffic_visit(VISITOR_C, "manga", now=NOW - timedelta(days=120))

    summary = await service.traffic_summary(now=NOW)

    assert summary.unique_visitors_7d == 2
    assert summary.unique_visitors_30d == 2
    assert summary.unique_visitors_today == 2
    assert summary.weekly_goal == 100
    assert summary.progress_percent == 2.0
    assert len(summary.daily) == 30
    assert summary.daily[-1].day == NOW.date()
    assert summary.daily[-1].unique_visitors == 2
    assert summary.last_visit_at is not None
    groups = {item.path_group: item.unique_visitors for item in summary.path_groups}
    # Visitor A appears on two days with different first-page groups, so the
    # per-section breakdown intentionally sums to more than unique_visitors_7d.
    assert groups == {"home": 1, "manga": 1, "catalogue": 1}
    assert "visitor_hash" not in summary.model_dump()
    await engine.dispose()


@pytest.mark.asyncio
async def test_service_purges_rows_older_than_90_days(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, engine = await make_service(tmp_path)
    async with service.session_factory() as session:
        await repository_record_traffic_visit(
            session,
            visitor_hash=VISITOR_C,
            path_group="home",
            visited_at=NOW - timedelta(days=120),
        )
        await session.commit()

    monkeypatch.setattr(service_module, "_last_traffic_cleanup", 0.0)
    accepted = await service.record_traffic_visit(VISITOR_A, "home", now=NOW)
    assert accepted is True
    async with engine.connect() as connection:
        rows = (
            await connection.execute(text("SELECT visitor_hash FROM traffic_visits"))
        ).fetchall()
    assert rows == [(VISITOR_A,)]
    await engine.dispose()


@pytest.mark.asyncio
async def test_traffic_table_has_no_pii_columns(tmp_path: Path) -> None:
    _, engine = await make_service(tmp_path)
    async with engine.connect() as connection:
        columns = {
            row[1]
            for row in (
                await connection.execute(text("PRAGMA table_info(traffic_visits)"))
            ).fetchall()
        }
    assert columns == {"id", "visitor_hash", "day", "path_group", "created_at"}
    assert not {"ip", "ip_address", "user_agent", "email", "user_id"} & columns
    await engine.dispose()
