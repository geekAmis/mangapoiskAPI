"""SQLite FTS5 mirror of the catalogue search document.

PostgreSQL uses ``pg_trgm`` GIN indexes.  SQLite has no trigram operator, so
without a mirror every keystroke would scan the whole table with a pile of LIKE
patterns.  FTS5 is built into the SQLite shipped with Python and gives us an
inverted index for the same normalized tokens, keeping local installs and tests
fast as well.

The table is intentionally *not* part of SQLAlchemy metadata: it is a SQLite
only optimisation and must never appear in PostgreSQL DDL.  The repository
falls back to LIKE if the table is absent (e.g. a very old SQLite file).
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_CREATE_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS manga_search_fts USING fts5(
    manga_id UNINDEXED,
    body,
    tokenize = 'unicode61 remove_diacritics 2'
)
"""


def is_sqlite(session: AsyncSession) -> bool:
    return session.get_bind().dialect.name == "sqlite"


async def fts_available(session: AsyncSession) -> bool:
    if not is_sqlite(session):
        return False
    value = await session.scalar(
        text(
            "SELECT 1 FROM sqlite_master "
            "WHERE type = 'table' AND name = 'manga_search_fts' LIMIT 1"
        )
    )
    return bool(value)


async def ensure_fts_table(session: AsyncSession) -> bool:
    if not is_sqlite(session):
        return False
    await session.execute(text(_CREATE_SQL))
    return True


async def sync_search_fts(session: AsyncSession, manga_id: uuid.UUID, body: str) -> None:
    """Replace one FTS row.  No-op on PostgreSQL or before the table exists."""

    if not is_sqlite(session):
        return
    if not await fts_available(session):
        return
    # SQLAlchemy stores UUID columns as 32-character hex on SQLite; keep the
    # mirror in the same representation so ``manga.id IN (...)`` joins work.
    identifier = manga_id.hex
    await session.execute(
        text("DELETE FROM manga_search_fts WHERE manga_id = :manga_id"),
        {"manga_id": identifier},
    )
    await session.execute(
        text("INSERT INTO manga_search_fts (manga_id, body) VALUES (:manga_id, :body)"),
        {"manga_id": identifier, "body": body},
    )


async def rebuild_search_fts(session: AsyncSession) -> int:
    """Full rebuild after a migration/backfill.  Returns indexed row count."""

    if not is_sqlite(session):
        return 0
    if not await ensure_fts_table(session):
        return 0
    await session.execute(text("DELETE FROM manga_search_fts"))
    result = await session.execute(
        text(
            "INSERT INTO manga_search_fts (manga_id, body) "
            "SELECT CAST(id AS TEXT), search_blob FROM manga"
        )
    )
    return int(result.rowcount or 0)
