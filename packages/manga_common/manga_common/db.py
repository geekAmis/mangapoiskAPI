from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, MetaData, Uuid, event, func
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .metrics import (
    record_db_lock_error,
    record_db_lock_exhausted,
    record_db_lock_recovered,
    record_db_lock_retry,
)

logger = logging.getLogger("manga_common.db")

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKey:
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


def _configure_sqlite(engine: AsyncEngine) -> None:
    """WAL + busy timeout make short writer batches coexist with readers.

    Without WAL a long migration transaction blocks every list/search query and
    a second process can turn that into ``database is locked``.  The timeout is
    a last-resort guard; the background worker also retries with backoff.
    """

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _record):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        try:
            # Timeout first: even a failed WAL switch should leave the
            # connection able to wait for a competing writer.
            cursor.execute("PRAGMA busy_timeout=15000")
            for pragma in (
                "journal_mode=WAL",
                "synchronous=NORMAL",
                "wal_autocheckpoint=1000",
            ):
                # Some network/read-only filesystems cannot use WAL; the
                # worker still retries lock errors with backoff.
                with contextlib.suppress(Exception):
                    cursor.execute(f"PRAGMA {pragma}")
        finally:
            cursor.close()


def create_engine(database_url: str, *, echo: bool = False, pool_size: int = 10) -> AsyncEngine:
    kwargs: dict[str, Any] = {"echo": echo, "pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        kwargs.pop("pool_size", None)
        engine = create_async_engine(database_url, **kwargs)
        _configure_sqlite(engine)
        return engine
    kwargs["pool_size"] = pool_size
    kwargs["max_overflow"] = pool_size
    return create_async_engine(database_url, **kwargs)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def session_scope(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception as exc:
            await session.rollback()
            # Write paths are not retried automatically: they need explicit
            # idempotency.  Still count the lock so /metrics and the watchdog
            # can distinguish "reader contention" from a real database error.
            if is_database_locked(exc):
                record_db_lock_error()
                logger.warning(
                    "sqlite lock during write transaction; not retried automatically"
                )
            raise


async def create_all(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def drop_all(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)


async def ping(engine: AsyncEngine) -> bool:
    from sqlalchemy import text

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def is_database_locked(exc: BaseException) -> bool:
    """True for SQLite's transient single-writer contention errors.

    Older SQLite builds report ``database table is locked`` for the same
    condition; ``database is busy`` is the WAL equivalent under heavy writer
    pressure.  None of these are permanent and a bounded read retry is safe.
    """

    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "database is locked",
            "database table is locked",
            "database is busy",
            "sqlite_busy",
        )
    )


async def retry_on_locked(
    operation: Callable[[], Awaitable[Any]],
    *,
    attempts: int = 3,
    base_delay: float = 0.2,
) -> Any:
    """Retry a read operation when SQLite reports a transient writer lock.

    Each attempt must open its own session so a rolled-back connection is not
    reused.  Write paths are intentionally not wrapped: their transactions must
    be retried by the caller with explicit idempotency semantics.
    """

    for attempt in range(1, attempts + 1):
        try:
            result = await operation()
            if attempt > 1:
                record_db_lock_recovered()
            return result
        except Exception as exc:
            if not is_database_locked(exc):
                raise
            record_db_lock_error()
            if attempt >= attempts:
                record_db_lock_exhausted()
                logger.warning(
                    "sqlite lock on read; retry budget exhausted after %s attempts",
                    attempts,
                )
                raise
            record_db_lock_retry()
            logger.warning(
                "sqlite lock on read; retrying attempt %s/%s",
                attempt + 1,
                attempts,
            )
            await asyncio.sleep(base_delay * (2 ** (attempt - 1)))
    raise AssertionError("unreachable")
