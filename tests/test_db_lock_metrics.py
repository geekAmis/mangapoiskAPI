from __future__ import annotations

import pytest
from manga_common.db import is_database_locked, retry_on_locked
from manga_common.metrics import metrics, reset_metrics


@pytest.mark.asyncio
async def test_retry_on_locked_counts_errors_retries_and_recovery() -> None:
    reset_metrics()
    calls = 0

    async def flaky() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RuntimeError("(sqlite3.OperationalError) database is locked")
        return "ok"

    assert await retry_on_locked(flaky, attempts=3, base_delay=0) == "ok"
    snapshot = metrics.db_lock_snapshot()
    assert snapshot["errors_total"] == 2
    assert snapshot["retries_total"] == 2
    assert snapshot["recovered_total"] == 1
    assert snapshot["exhausted_total"] == 0
    assert snapshot["errors_1m"] == 2


@pytest.mark.asyncio
async def test_retry_on_locked_counts_exhausted_budget() -> None:
    reset_metrics()

    async def always_locked() -> None:
        raise RuntimeError("database table is locked")

    with pytest.raises(RuntimeError, match="locked"):
        await retry_on_locked(always_locked, attempts=2, base_delay=0)

    snapshot = metrics.db_lock_snapshot()
    assert snapshot["errors_total"] == 2
    assert snapshot["retries_total"] == 1
    assert snapshot["exhausted_total"] == 1


def test_lock_classifier_accepts_sqlite_variants() -> None:
    assert is_database_locked(RuntimeError("database is locked"))
    assert is_database_locked(RuntimeError("database table is locked"))
    assert is_database_locked(RuntimeError("database is busy"))
    assert is_database_locked(RuntimeError("sqlite_busy"))
    assert not is_database_locked(RuntimeError("no such table: manga"))
