"""Batched, resumable URL-slug backfill.

The v1.2 catalogue has ~78k rows and no public URL slug.  Computing the
transliterated slug for every row at startup would hold the SQLite write lock
for minutes and delay health checks, so startup only adds the column/index and
this worker fills rows in small committed batches.  Every read path computes a
slug on demand as a fallback, which means slug URLs work immediately even
before the worker has reached a particular title.

The worker is idempotent: a restart simply selects the rows whose ``url_slug``
is still empty.  It never overwrites a stored slug, so indexed URLs stay
stable when a source later changes a title.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .repository import backfill_url_slugs

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 500
DEFAULT_YIELD_SECONDS = 0.05


async def run_slug_backfill(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    yield_seconds: float = DEFAULT_YIELD_SECONDS,
    max_batches: int | None = None,
) -> int:
    """Fill missing slugs until no rows remain.

    Returns the number of rows updated.  ``max_batches`` is used by tests and
    manual one-off runs; production leaves it ``None`` so the worker drains the
    backlog and exits.
    """

    total = 0
    batches = 0
    while True:
        async with session_factory() as session:
            updated = await backfill_url_slugs(session, batch_size=batch_size)
            await session.commit()
        total += updated
        batches += 1
        if updated < batch_size:
            break
        if max_batches is not None and batches >= max_batches:
            break
        if yield_seconds > 0:
            await asyncio.sleep(yield_seconds)
    if total:
        logger.info("url-slug backfill complete: %s rows in %s batches", total, batches)
    else:
        logger.debug("url-slug backfill: nothing to do")
    return total


async def run_slug_backfill_safe(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    yield_seconds: float = DEFAULT_YIELD_SECONDS,
) -> None:
    """Background-task wrapper: never let a slug failure affect health."""

    try:
        await run_slug_backfill(
            session_factory,
            batch_size=batch_size,
            yield_seconds=yield_seconds,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("url-slug backfill failed; read paths still compute slugs on demand")
