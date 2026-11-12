"""Batched, resumable catalogue search backfill.

Startup only performs additive schema changes and a quick marker update.  The
expensive Python normalization (transliteration, skeletons, synonyms) runs here,
in small transactions with yields between batches.  Progress is stored in
``search_backfill_state`` and the worker uses a short lease so two catalog
processes do not normalize the same rows.

Rows with ``search_indexed = false`` remain searchable:
    * SQLite gets an immediate FTS5 mirror built from the legacy columns;
    * PostgreSQL candidates include legacy ``lower(title) LIKE`` conditions;
    * the ranker builds normalized fields on demand for such rows.

The worker is safe to kill at any point: each batch is committed atomically and
the next run starts from the remaining ``search_indexed = false`` rows.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import bindparam, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models import Manga, SearchBackfillState
from .normalization import genres_key, status_key
from .repository import compute_group_key
from .search import build_search_fields
from .search_fts import fts_row_count, rebuild_legacy_fts, sync_search_fts_many

logger = logging.getLogger(__name__)

STATE_ID = 1


@dataclass(frozen=True)
class BackfillConfig:
    batch_size: int = 500
    lease_seconds: int = 120
    yield_seconds: float = 0.01
    max_retries: int = 5
    retry_base_seconds: float = 0.5


def _now() -> datetime:
    return datetime.now(UTC)


def _is_locked(exc: BaseException) -> bool:
    if not isinstance(exc, OperationalError):
        return False
    message = str(exc).lower()
    return "locked" in message or "busy" in message


async def retry_on_locked[T](
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int = 5,
    base_delay: float = 0.5,
) -> T:
    """Retry SQLite lock/busy failures with exponential backoff."""

    for attempt in range(max(1, attempts)):
        try:
            return await operation()
        except OperationalError as exc:
            if not _is_locked(exc) or attempt >= attempts - 1:
                raise
            delay = base_delay * (2**attempt)
            logger.warning(
                "catalogue database is locked; retrying in %.1fs (%s/%s)",
                delay,
                attempt + 1,
                attempts,
            )
            await asyncio.sleep(delay)
    raise AssertionError("unreachable")


async def ensure_state(session: AsyncSession) -> SearchBackfillState:
    state = await session.get(SearchBackfillState, STATE_ID)
    if state is not None:
        return state
    state = SearchBackfillState(
        id=STATE_ID,
        status="pending",
        total=0,
        normalized=0,
        legacy_indexed=0,
        failed=0,
        batch_size=0,
    )
    session.add(state)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        state = await session.get(SearchBackfillState, STATE_ID)
        if state is None:
            raise
    return state


async def _counts(session: AsyncSession) -> tuple[int, int]:
    total = int((await session.scalar(select(func.count(Manga.id)))) or 0)
    normalized = int(
        (
            await session.scalar(
                select(func.count(Manga.id)).where(Manga.search_indexed.is_(True))
            )
        )
        or 0
    )
    return total, normalized


async def _acquire_lease(
    session: AsyncSession, owner: str, lease_seconds: int
) -> bool:
    await ensure_state(session)
    now = _now()
    result = await session.execute(
        update(SearchBackfillState)
        .where(
            SearchBackfillState.id == STATE_ID,
            or_(
                SearchBackfillState.lease_owner.is_(None),
                SearchBackfillState.lease_until.is_(None),
                SearchBackfillState.lease_until < now,
                SearchBackfillState.lease_owner == owner,
            ),
        )
        .values(
            lease_owner=owner,
            lease_until=now + timedelta(seconds=lease_seconds),
        )
    )
    return bool(result.rowcount)


async def release_lease(session_factory: async_sessionmaker[AsyncSession], owner: str) -> None:
    async with session_factory() as session:
        await session.execute(
            update(SearchBackfillState)
            .where(
                SearchBackfillState.id == STATE_ID,
                SearchBackfillState.lease_owner == owner,
            )
            .values(lease_owner=None, lease_until=None)
        )
        await session.commit()


async def bootstrap_search_index(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    batch_size: int = 500,
) -> dict[str, int]:
    """Make legacy rows searchable before the first HTTP request.

    The SQLite FTS mirror is filled from raw legacy columns in one or two
    statements (measured at ~2.5s for 78k rows), so search/suggest keep working
    while Python normalization runs in the background.
    """

    async with session_factory() as session:
        state = await ensure_state(session)
        total, normalized = await _counts(session)
        pending = max(0, total - normalized)
        legacy = 0
        if pending:
            legacy = await rebuild_legacy_fts(session)
        state.total = total
        state.normalized = normalized
        state.legacy_indexed = legacy or (await fts_row_count(session))
        state.batch_size = batch_size
        state.failed = 0
        state.status = "completed" if pending == 0 else "pending"
        state.last_error = None
        if pending == 0:
            state.finished_at = _now()
            state.lease_owner = None
            state.lease_until = None
        await session.commit()
        logger.info(
            "search bootstrap: total=%s normalized=%s pending=%s legacy=%s",
            total,
            normalized,
            pending,
            legacy,
        )
        return {"total": total, "normalized": normalized, "pending": pending, "legacy": legacy}


def _prepare_rows(rows: Sequence[Any]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for row in rows:
        fields = build_search_fields(
            title=row.title,
            title_en=row.title_en,
            title_alt=row.title_alt,
            genres=row.genres or [],
            content_type=row.content_type,
            description=row.description,
            metadata=row.metadata_json or {},
        )
        group_key = row.group_key or compute_group_key(row.title)
        prepared.append(
            {
                "manga_id": row.manga_id,
                "group_key": group_key,
                "genres_key": genres_key(row.genres or []),
                "status_key": status_key(row.status),
                **fields,
                "search_indexed": True,
            }
        )
    return prepared


async def _write_state(
    session: AsyncSession,
    *,
    status: str,
    total: int,
    normalized: int,
    batch_size: int,
    lease_seconds: int,
    owner: str,
    legacy_indexed: int | None = None,
    last_error: str | None = None,
) -> None:
    state = await ensure_state(session)
    now = _now()
    state.status = status
    state.total = total
    state.normalized = normalized
    # ``failed`` means a batch error, not "rows still pending"; the latter is
    # always derivable as ``remaining`` in the stats schema.
    state.failed = 0
    state.batch_size = batch_size
    if legacy_indexed is not None:
        state.legacy_indexed = legacy_indexed
    if state.started_at is None and normalized < total:
        state.started_at = now
    started_at = state.started_at
    if started_at is not None and started_at.tzinfo is None:
        # SQLite drops tzinfo even for DateTime(timezone=True).
        started_at = started_at.replace(tzinfo=UTC)
    if started_at is not None and normalized > 0:
        elapsed = max(0.001, (now - started_at).total_seconds())
        rate = normalized / elapsed
        state.rate_per_second = round(rate, 2)
        remaining = max(0, total - normalized)
        state.eta_seconds = int(remaining / rate) if rate > 0 else None
    if last_error is not None:
        state.last_error = last_error[:4000]
    if status == "completed":
        state.finished_at = now
        state.eta_seconds = 0
        state.lease_owner = None
        state.lease_until = None
    else:
        state.lease_owner = owner
        state.lease_until = now + timedelta(seconds=lease_seconds)


async def _apply_batch(session: AsyncSession, prepared: Sequence[dict[str, Any]]) -> None:
    if not prepared:
        return
    table = Manga.__table__
    statement = (
        table.update()
        .where(table.c.id == bindparam("manga_id"))
        .values(
            search_title=bindparam("search_title"),
            search_alt=bindparam("search_alt"),
            search_names=bindparam("search_names"),
            search_meta=bindparam("search_meta"),
            search_description=bindparam("search_description"),
            search_blob=bindparam("search_blob"),
            search_indexed=True,
            group_key=bindparam("group_key"),
            genres_key=bindparam("genres_key"),
            status_key=bindparam("status_key"),
        )
    )
    await session.execute(statement, list(prepared))
    await sync_search_fts_many(
        session,
        [
            (item["manga_id"], item["search_blob"])
            for item in prepared
        ],
    )


class SearchBackfillWorker:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        config: BackfillConfig | None = None,
        *,
        owner: str | None = None,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.config = config or BackfillConfig()
        self.owner = owner or f"catalog-{uuid.uuid4().hex[:12]}"
        self.on_progress = on_progress

    async def step(self) -> int | None:
        """Normalize one batch.  Returns 0 when done, None if another worker owns the lease."""

        async with self.session_factory() as session:
            if not await _acquire_lease(session, self.owner, self.config.lease_seconds):
                await session.rollback()
                return None
            # Make the lease visible to other processes before doing CPU work.
            await session.commit()

            rows = (
                await session.execute(
                    select(
                        Manga.id.label("manga_id"),
                        Manga.title,
                        Manga.title_en,
                        Manga.title_alt,
                        Manga.description,
                        Manga.genres,
                        Manga.content_type,
                        Manga.metadata_json.label("metadata_json"),
                        Manga.status,
                        Manga.group_key,
                    )
                    .where(Manga.search_indexed.is_(False))
                    .order_by(Manga.id)
                    .limit(self.config.batch_size)
                )
            ).all()
            if not rows:
                total, normalized = await _counts(session)
                await _write_state(
                    session,
                    status="completed",
                    total=total,
                    normalized=normalized,
                    batch_size=self.config.batch_size,
                    lease_seconds=self.config.lease_seconds,
                    owner=self.owner,
                )
                await session.commit()
                return 0

            prepared = await asyncio.to_thread(_prepare_rows, rows)
            try:
                await _apply_batch(session, prepared)
                total, normalized = await _counts(session)
                await _write_state(
                    session,
                    status="running",
                    total=total,
                    normalized=normalized,
                    batch_size=self.config.batch_size,
                    lease_seconds=self.config.lease_seconds,
                    owner=self.owner,
                )
                await session.commit()
            except Exception:
                await session.rollback()
                raise

        progress = {
            "batch": len(prepared),
            "total": total,
            "normalized": normalized,
            "remaining": max(0, total - normalized),
        }
        if self.on_progress is not None:
            self.on_progress(progress)
        logger.info(
            "search backfill progress: %s/%s (%.1f%%), batch=%s, remaining=%s",
            normalized,
            total,
            (normalized / total * 100) if total else 100.0,
            len(prepared),
            progress["remaining"],
        )
        await asyncio.sleep(self.config.yield_seconds)
        return len(prepared)

    async def _record_failure(self, exc: BaseException) -> None:
        async with self.session_factory() as session:
            state = await ensure_state(session)
            total, normalized = await _counts(session)
            state.status = "failed"
            state.total = total
            state.normalized = normalized
            state.failed = max(0, total - normalized)
            state.last_error = f"{type(exc).__name__}: {exc}"[:4000]
            state.lease_owner = None
            state.lease_until = None
            await session.commit()

    async def backfill(self) -> int:
        processed = 0
        failures = 0
        while True:
            try:
                batch = await retry_on_locked(
                    self.step,
                    attempts=self.config.max_retries,
                    base_delay=self.config.retry_base_seconds,
                )
                failures = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                failures += 1
                logger.exception("search backfill batch failed")
                await self._record_failure(exc)
                if failures > self.config.max_retries:
                    logger.error("search backfill paused after %s failures", failures)
                    return processed
                await asyncio.sleep(min(300.0, self.config.retry_base_seconds * 2**failures))
                continue
            if batch is None:
                # Another catalog process is doing the work, or a dead process
                # still holds the lease.  Wait for expiry, then resume.
                await asyncio.sleep(min(float(self.config.lease_seconds), 30.0))
                continue
            if batch == 0:
                return processed
            processed += batch

    async def backfill_group_keys(self) -> int:
        processed = 0
        while True:
            async with self.session_factory() as session:
                rows = (
                    await session.execute(
                        select(Manga.id.label("manga_id"), Manga.title)
                        .where(or_(Manga.group_key.is_(None), Manga.group_key == ""))
                        .order_by(Manga.id)
                        .limit(self.config.batch_size)
                    )
                ).all()
                if not rows:
                    return processed
                prepared = [
                    {
                        "manga_id": row.manga_id,
                        "group_key": compute_group_key(row.title)
                        or f"manga-{row.manga_id}",
                    }
                    for row in rows
                ]
                table = Manga.__table__
                await session.execute(
                    table.update()
                    .where(table.c.id == bindparam("manga_id"))
                    .values(group_key=bindparam("group_key")),
                    prepared,
                )
                await session.commit()
                processed += len(prepared)
                await asyncio.sleep(self.config.yield_seconds)

    async def backfill_cover_group_keys(self) -> int:
        processed = 0
        while True:
            async with self.session_factory() as session:
                result = await session.execute(
                    text(
                        "UPDATE manga_covers SET group_key = "
                        "(SELECT group_key FROM manga "
                        "WHERE manga.id = manga_covers.manga_id) "
                        "WHERE id IN (SELECT id FROM manga_covers "
                        "WHERE group_key IS NULL LIMIT :limit)"
                    ),
                    {"limit": self.config.batch_size},
                )
                await session.commit()
                count = int(result.rowcount or 0)
                if count == 0:
                    return processed
                processed += count
                await asyncio.sleep(self.config.yield_seconds)

    async def run(self) -> None:
        try:
            processed = await self.backfill()
            if processed:
                logger.info("search backfill finished: %s rows normalized", processed)
            await self.backfill_group_keys()
            await self.backfill_cover_group_keys()
        finally:
            try:
                await release_lease(self.session_factory, self.owner)
            except Exception:
                # Lease expiry is the fallback; shutdown must not raise here.
                logger.warning("could not release search backfill lease", exc_info=True)
