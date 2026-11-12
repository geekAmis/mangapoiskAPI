from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger("catalog.sql")


def install_slow_query_logging(engine: AsyncEngine, *, threshold_ms: int = 500) -> None:
    """Log SQL statements that take longer than ``threshold_ms``.

    Request middleware already logs the overall duration, but this listener
    separates the expensive statement (for example a stale-statistics count)
    from serialization and network time.  Parameters are intentionally omitted:
    the statement shape and duration are enough to identify the regression
    without leaking titles or user data into logs.
    """

    if getattr(engine.sync_engine, "_catalog_slow_query_logging", False):
        return
    engine.sync_engine._catalog_slow_query_logging = True  # type: ignore[attr-defined]

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _before_cursor_execute(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        context._catalog_query_started = time.perf_counter()

    @event.listens_for(engine.sync_engine, "after_cursor_execute")
    def _after_cursor_execute(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        started = getattr(context, "_catalog_query_started", None)
        if started is None:
            return
        elapsed_ms = (time.perf_counter() - started) * 1000
        if elapsed_ms < threshold_ms:
            return
        compact = " ".join(statement.split())
        logger.warning(
            "slow SQL %.1fms: %s",
            elapsed_ms,
            compact[:500],
            extra={
                "event": "catalog_slow_sql",
                "duration_ms": round(elapsed_ms, 2),
                "executemany": executemany,
            },
        )


def install_sqlite_optimize_on_close(engine: AsyncEngine) -> None:
    """Run a bounded ``PRAGMA optimize`` when a SQLite connection is closed.

    SQLite recommends this hook instead of scheduling a full ``ANALYZE``: it
    only re-samples tables whose planner statistics are stale.  The analysis
    limit keeps the work bounded even on the 1.7M-row chapter table.
    """

    if engine.dialect.name != "sqlite":
        return
    if getattr(engine.sync_engine, "_catalog_optimize_on_close", False):
        return
    engine.sync_engine._catalog_optimize_on_close = True  # type: ignore[attr-defined]

    @event.listens_for(engine.sync_engine, "close")
    def _optimize_on_close(dbapi_connection: Any, record: Any) -> None:
        try:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA analysis_limit=400")
                cursor.execute("PRAGMA optimize")
            finally:
                cursor.close()
        except Exception:  # pragma: no cover - best-effort maintenance
            logger.debug("PRAGMA optimize on close failed", exc_info=True)
