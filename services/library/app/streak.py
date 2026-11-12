from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from manga_common.schemas import StreakOut

from .repository import as_utc

DEFAULT_TIMEZONE = "UTC"
MAX_TIMEZONE_LENGTH = 64


def resolve_timezone(name: str | None) -> tuple[str, ZoneInfo]:
    """Return a safe IANA timezone; unknown input degrades to UTC."""

    candidate = (name or "").strip()[:MAX_TIMEZONE_LENGTH]
    if not candidate:
        return DEFAULT_TIMEZONE, ZoneInfo(DEFAULT_TIMEZONE)
    try:
        return candidate, ZoneInfo(candidate)
    except (ZoneInfoNotFoundError, ValueError):
        return DEFAULT_TIMEZONE, ZoneInfo(DEFAULT_TIMEZONE)


def _local_days(timestamps: list[datetime], timezone: ZoneInfo) -> set[date]:
    days: set[date] = set()
    for timestamp in timestamps:
        moment = as_utc(timestamp)
        if moment is not None:
            days.add(moment.astimezone(timezone).date())
    return days


def compute_streak(
    timestamps: list[datetime],
    *,
    timezone: str | None = None,
    now: datetime | None = None,
) -> StreakOut:
    """Count consecutive reading days in the reader's timezone.

    The streak is intentionally forgiving: a user who has not read yet today
    keeps yesterday's streak until the local day ends.  Missing today is never
    shown as a broken streak or as a punishment.
    """

    tz_name, tz = resolve_timezone(timezone)
    moment = as_utc(now) or datetime.now(UTC)
    today = moment.astimezone(tz).date()
    days = _local_days(timestamps, tz)

    if not days:
        return StreakOut(timezone=tz_name)

    anchor: date | None = None
    if today in days:
        anchor = today
    elif today - timedelta(days=1) in days:
        anchor = today - timedelta(days=1)

    current = 0
    cursor = anchor
    while cursor is not None and cursor in days:
        current += 1
        cursor -= timedelta(days=1)

    longest = 0
    run = 0
    previous: date | None = None
    for day in sorted(days):
        if previous is not None and day == previous + timedelta(days=1):
            run += 1
        else:
            run = 1
        longest = max(longest, run)
        previous = day

    recent = sorted(days)[-30:]
    return StreakOut(
        current=current,
        longest=longest,
        read_today=today in days,
        timezone=tz_name,
        last_read_on=max(days).isoformat(),
        days=[day.isoformat() for day in recent],
    )
