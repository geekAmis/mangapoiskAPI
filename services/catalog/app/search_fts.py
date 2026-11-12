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
from collections.abc import Sequence

from sqlalchemy import bindparam, text
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


async def sync_search_fts_many(
    session: AsyncSession, rows: Sequence[tuple[uuid.UUID, str]]
) -> None:
    """Replace a batch of FTS rows with two statements (delete + executemany)."""

    if not rows or not is_sqlite(session):
        return
    if not await fts_available(session):
        return
    identifiers = [manga_id.hex for manga_id, _body in rows]
    await session.execute(
        text("DELETE FROM manga_search_fts WHERE manga_id IN :ids").bindparams(
            bindparam("ids", expanding=True)
        ),
        {"ids": identifiers},
    )
    await session.execute(
        text("INSERT INTO manga_search_fts (manga_id, body) VALUES (:manga_id, :body)"),
        [
            {"manga_id": manga_id.hex, "body": body}
            for manga_id, body in rows
        ],
    )


_LEGACY_BODY_SQL = (
    "coalesce(title, '') || ' ' || coalesce(title_en, '') || ' ' || "
    "coalesce(title_alt, '') || ' ' || coalesce(description, '') || ' ' || "
    "coalesce(genres, '[]') || ' ' || coalesce(content_type, '')"
)


async def rebuild_legacy_fts(session: AsyncSession, *, pending_only: bool = True) -> int:
    """Make unindexed rows searchable immediately using their legacy columns.

    SQLite's FTS5 tokenizer folds Unicode case, unlike ``lower()``, so copying
    the original title/description into FTS is enough for the fallback to match
    Russian queries while the Python normalizer is still running in the
    background.  ``pending_only`` avoids touching already indexed rows.
    """

    if not is_sqlite(session):
        return 0
    if not await ensure_fts_table(session):
        return 0
    if pending_only:
        await session.execute(
            text(
                "DELETE FROM manga_search_fts WHERE manga_id IN "
                "(SELECT CAST(id AS TEXT) FROM manga WHERE search_indexed = 0)"
            )
        )
        result = await session.execute(
            text(
                "INSERT INTO manga_search_fts (manga_id, body) "
                f"SELECT CAST(id AS TEXT), {_LEGACY_BODY_SQL} "
                "FROM manga WHERE search_indexed = 0"
            )
        )
        return int(result.rowcount or 0)

    await session.execute(text("DELETE FROM manga_search_fts"))
    result = await session.execute(
        text(
            "INSERT INTO manga_search_fts (manga_id, body) "
            "SELECT CAST(id AS TEXT), CASE WHEN search_indexed = 1 "
            f"THEN search_blob ELSE {_LEGACY_BODY_SQL} END FROM manga"
        )
    )
    return int(result.rowcount or 0)


async def rebuild_search_fts(session: AsyncSession) -> int:
    """Full rebuild after a migration/backfill.  Returns indexed row count."""

    return await rebuild_legacy_fts(session, pending_only=False)


async def fts_row_count(session: AsyncSession) -> int:
    if not is_sqlite(session) or not await fts_available(session):
        return 0
    return int((await session.scalar(text("SELECT count(*) FROM manga_search_fts"))) or 0)
