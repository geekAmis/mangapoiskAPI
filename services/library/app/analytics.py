from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from manga_common.schemas import AnalyticsRetentionCohort, AnalyticsRetentionOut

from .models import AnalyticsEvent
from .repository import as_utc


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def compute_retention(
    events: list[AnalyticsEvent], *, days: int = 30, now: datetime | None = None
) -> AnalyticsRetentionOut:
    """Weekly cohorts with D1/D7/D30 return rates.

    This is deliberately aggregate-only: no account id, IP or user agent is
    stored.  ``client_id`` is a random device-local identifier, so the query can
    count returning devices without identifying people.
    """

    moment = as_utc(now) or datetime.now(UTC)
    first_seen: dict[str, date] = {}
    active_days: dict[str, set[date]] = defaultdict(set)
    for event in events:
        created = as_utc(event.created_at)
        if created is None:
            continue
        client = event.client_id
        day = created.astimezone(UTC).date()
        active_days[client].add(day)
        current = first_seen.get(client)
        if current is None or day < current:
            first_seen[client] = day

    since = moment.astimezone(UTC).date() - timedelta(days=max(1, min(days, 90)))
    cohorts: dict[date, list[str]] = defaultdict(list)
    for client, day in first_seen.items():
        if day < since:
            continue
        cohorts[_week_start(day)].append(client)

    result: list[AnalyticsRetentionCohort] = []
    for cohort_day in sorted(cohorts):
        clients = cohorts[cohort_day]
        d1 = d7 = d30 = 0
        size = len(clients)
        for client in clients:
            start = first_seen[client]
            active = active_days[client]
            if start + timedelta(days=1) in active:
                d1 += 1
            if start + timedelta(days=7) in active:
                d7 += 1
            if start + timedelta(days=30) in active:
                d30 += 1
        result.append(
            AnalyticsRetentionCohort(
                cohort=cohort_day.isoformat(),
                size=size,
                d1=d1,
                d7=d7,
                d30=d30,
                d1_rate=round(d1 / size, 4) if size else 0.0,
                d7_rate=round(d7 / size, 4) if size else 0.0,
                d30_rate=round(d30 / size, 4) if size else 0.0,
            )
        )
    return AnalyticsRetentionOut(days=days, generated_at=moment, cohorts=result)
