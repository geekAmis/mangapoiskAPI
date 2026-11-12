from __future__ import annotations

import logging

from manga_common.db import Base
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine

from .models import Manga
from .normalization import genres_key, status_key
from .search import build_search_fields

logger = logging.getLogger(__name__)

_SEARCH_COLUMNS = (
    "search_title",
    "search_alt",
    "search_names",
    "search_meta",
    "search_description",
    "search_blob",
)


async def _try_extension(connection, statement: str, name: str) -> bool:
    """Create an optional extension without aborting the whole migration."""

    try:
        async with connection.begin_nested():
            await connection.execute(text(statement))
        return True
    except Exception as exc:  # pragma: no cover - depends on server privileges
        logger.warning("could not enable %s: %s", name, exc)
        return False


async def ensure_runtime_schema(engine: AsyncEngine) -> None:
    """Additive migrations for existing SQLite/Postgres databases.

    ``create_all`` creates new tables but never new columns.  The project keeps
    a tiny forward-only migration here so an existing deployed catalogue does
    not need a full Alembic setup for these additive fields.
    """

    dialect = engine.dialect.name
    async with engine.begin() as connection:
        # New tables are also created by ``create_all``; doing it here keeps
        # older deployments and direct ``ensure_runtime_schema`` calls safe.
        await connection.run_sync(Base.metadata.create_all)
        if dialect == "sqlite":
            result = await connection.execute(text("PRAGMA table_info(chapters)"))
            chapter_columns = {row[1] for row in result.fetchall()}
            if "translator" not in chapter_columns:
                await connection.execute(
                    text("ALTER TABLE chapters ADD COLUMN translator VARCHAR(255)")
                )
            result = await connection.execute(text("PRAGMA table_info(manga)"))
            manga_columns = {row[1] for row in result.fetchall()}
            if "group_key" not in manga_columns:
                await connection.execute(
                    text("ALTER TABLE manga ADD COLUMN group_key VARCHAR(255)")
                )
            if "status_key" not in manga_columns:
                await connection.execute(
                    text("ALTER TABLE manga ADD COLUMN status_key VARCHAR(64)")
                )
            if "genres_key" not in manga_columns:
                await connection.execute(text("ALTER TABLE manga ADD COLUMN genres_key TEXT"))
            if "enrichment_attempts" not in manga_columns:
                await connection.execute(
                    text(
                        "ALTER TABLE manga ADD COLUMN enrichment_attempts INTEGER NOT NULL DEFAULT 0"
                    )
                )
            if "enrichment_retry_at" not in manga_columns:
                await connection.execute(
                    text("ALTER TABLE manga ADD COLUMN enrichment_retry_at DATETIME")
                )
            if "enrichment_last_attempt_at" not in manga_columns:
                await connection.execute(
                    text("ALTER TABLE manga ADD COLUMN enrichment_last_attempt_at DATETIME")
                )
            if "enrichment_last_error" not in manga_columns:
                await connection.execute(
                    text("ALTER TABLE manga ADD COLUMN enrichment_last_error TEXT")
                )
            for column in _SEARCH_COLUMNS:
                if column not in manga_columns:
                    await connection.execute(
                        text(f"ALTER TABLE manga ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
                    )
            await connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_manga_group_key ON manga (group_key)")
            )
            await connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_manga_status_key ON manga (status_key)")
            )
            await connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_manga_last_synced_at ON manga (last_synced_at)"
                )
            )
            await connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_manga_search_title "
                    "ON manga (search_title)"
                )
            )
            await connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_manga_enrichment_retry_at "
                    "ON manga (enrichment_retry_at)"
                )
            )
            result = await connection.execute(text("PRAGMA table_info(crawl_state)"))
            crawl_columns = {row[1] for row in result.fetchall()}
            if "last_success_at" not in crawl_columns:
                await connection.execute(
                    text("ALTER TABLE crawl_state ADD COLUMN last_success_at DATETIME")
                )
            if "failure_count" not in crawl_columns:
                await connection.execute(
                    text(
                        "ALTER TABLE crawl_state ADD COLUMN failure_count "
                        "INTEGER NOT NULL DEFAULT 0"
                    )
                )
            if "failure_kind" not in crawl_columns:
                await connection.execute(
                    text("ALTER TABLE crawl_state ADD COLUMN failure_kind VARCHAR(32)")
                )
            if "eta_seconds" not in crawl_columns:
                await connection.execute(
                    text("ALTER TABLE crawl_state ADD COLUMN eta_seconds INTEGER")
                )
            await connection.execute(
                text(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS manga_search_fts USING fts5("
                    "manga_id UNINDEXED, body, "
                    "tokenize = 'unicode61 remove_diacritics 2')"
                )
            )
        else:
            await connection.execute(
                text("ALTER TABLE chapters ADD COLUMN IF NOT EXISTS translator VARCHAR(255)")
            )
            await connection.execute(
                text("ALTER TABLE manga ADD COLUMN IF NOT EXISTS group_key VARCHAR(255)")
            )
            await connection.execute(
                text("ALTER TABLE manga ADD COLUMN IF NOT EXISTS status_key VARCHAR(64)")
            )
            await connection.execute(
                text("ALTER TABLE manga ADD COLUMN IF NOT EXISTS genres_key TEXT")
            )
            for column in _SEARCH_COLUMNS:
                await connection.execute(
                    text(
                        f"ALTER TABLE manga ADD COLUMN IF NOT EXISTS "
                        f"{column} TEXT NOT NULL DEFAULT ''"
                    )
                )
            await connection.execute(
                text(
                    "ALTER TABLE manga ADD COLUMN IF NOT EXISTS "
                    "enrichment_attempts INTEGER NOT NULL DEFAULT 0"
                )
            )
            await connection.execute(
                text(
                    "ALTER TABLE manga ADD COLUMN IF NOT EXISTS "
                    "enrichment_retry_at TIMESTAMPTZ"
                )
            )
            await connection.execute(
                text(
                    "ALTER TABLE manga ADD COLUMN IF NOT EXISTS "
                    "enrichment_last_attempt_at TIMESTAMPTZ"
                )
            )
            await connection.execute(
                text(
                    "ALTER TABLE manga ADD COLUMN IF NOT EXISTS enrichment_last_error TEXT"
                )
            )
            await connection.execute(
                text("ALTER TABLE crawl_state ADD COLUMN IF NOT EXISTS last_success_at TIMESTAMPTZ")
            )
            await connection.execute(
                text(
                    "ALTER TABLE crawl_state ADD COLUMN IF NOT EXISTS "
                    "failure_count INTEGER NOT NULL DEFAULT 0"
                )
            )
            await connection.execute(
                text(
                    "ALTER TABLE crawl_state ADD COLUMN IF NOT EXISTS failure_kind VARCHAR(32)"
                )
            )
            await connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_manga_group_key ON manga (group_key)")
            )
            await connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_manga_status_key ON manga (status_key)")
            )
            await connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_manga_last_synced_at ON manga (last_synced_at)")
            )
            await connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_manga_search_title "
                    "ON manga (search_title)"
                )
            )
            await connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_manga_enrichment_retry_at "
                    "ON manga (enrichment_retry_at)"
                )
            )
            await connection.execute(
                text("ALTER TABLE crawl_state ADD COLUMN IF NOT EXISTS eta_seconds INTEGER")
            )
            await connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_manga_search_title_pattern "
                    "ON manga (search_title text_pattern_ops)"
                )
            )

            # pg_trgm accelerates the LIKE '%term%' candidate filter used by
            # both search and suggestions.  unaccent is kept as a deployment
            # safety net for SQL-level diagnostics; application matching is
            # already accent-insensitive because documents and queries are
            # normalised in Python.
            trigram = await _try_extension(
                connection, "CREATE EXTENSION IF NOT EXISTS pg_trgm", "pg_trgm"
            )
            await _try_extension(
                connection, "CREATE EXTENSION IF NOT EXISTS unaccent", "unaccent"
            )
            if trigram:
                for name, column in (
                    ("ix_manga_search_names_trgm", "search_names"),
                    ("ix_manga_search_title_trgm", "search_title"),
                    ("ix_manga_search_blob_trgm", "search_blob"),
                ):
                    try:
                        async with connection.begin_nested():
                            await connection.execute(
                                text(
                                    f"CREATE INDEX IF NOT EXISTS {name} "
                                    f"ON manga USING gin ({column} gin_trgm_ops)"
                                )
                            )
                    except Exception as exc:  # pragma: no cover - server specific
                        logger.warning("could not create %s: %s", name, exc)

        # Backfill filter keys and the denormalised search document.  This is
        # intentionally done in Python: it works on both dialects and keeps the
        # ranking identical to what write paths produce.
        rows = (
            await connection.execute(
                select(
                    Manga.id,
                    Manga.title,
                    Manga.title_en,
                    Manga.title_alt,
                    Manga.description,
                    Manga.genres,
                    Manga.content_type,
                    Manga.metadata_json.label("metadata_json"),
                    Manga.group_key,
                    Manga.status,
                    Manga.genres_key,
                    Manga.status_key,
                    Manga.search_blob,
                )
            )
        ).all()
        updated = 0
        for row in rows:
            expected_genres = genres_key(row.genres or [])
            expected_status = status_key(row.status)
            fields = build_search_fields(
                title=row.title,
                title_en=row.title_en,
                title_alt=row.title_alt,
                genres=row.genres or [],
                content_type=row.content_type,
                description=row.description,
                metadata=row.metadata_json or {},
            )
            values = {
                "genres_key": expected_genres,
                "status_key": expected_status,
                **fields,
            }
            if (
                row.genres_key != expected_genres
                or row.status_key != expected_status
                or row.search_blob != values["search_blob"]
            ):
                await connection.execute(
                    update(Manga).where(Manga.id == row.id).values(**values)
                )
                updated += 1
        if updated:
            logger.info("backfilled search/filter fields for %s catalogue entries", updated)

        if dialect == "sqlite":
            # The FTS mirror is rebuilt atomically with the migration: a stale
            # mirror would make suggestions miss titles after a schema upgrade.
            await connection.execute(text("DELETE FROM manga_search_fts"))
            await connection.execute(
                text(
                    "INSERT INTO manga_search_fts (manga_id, body) "
                    "SELECT CAST(id AS TEXT), search_blob FROM manga"
                )
            )

        # Covers created before grouping support need the denormalised key.
        await connection.execute(
            text(
                "UPDATE manga_covers SET group_key = "
                "(SELECT group_key FROM manga WHERE manga.id = manga_covers.manga_id) "
                "WHERE group_key IS NULL"
            )
        )

    logger.info("catalogue runtime schema is up to date")
