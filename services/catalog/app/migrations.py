from __future__ import annotations

import logging

from manga_common.db import Base, create_session_factory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from .repository import CATALOG_CARDS_VERSION, ensure_catalog_groups

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
            if "url_slug" not in manga_columns:
                await connection.execute(
                    text("ALTER TABLE manga ADD COLUMN url_slug VARCHAR(255)")
                )
            if "has_chapters" not in manga_columns:
                await connection.execute(
                    text(
                        "ALTER TABLE manga ADD COLUMN has_chapters "
                        "INTEGER NOT NULL DEFAULT 0"
                    )
                )
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
            if "search_indexed" not in manga_columns:
                await connection.execute(
                    text(
                        "ALTER TABLE manga ADD COLUMN search_indexed "
                        "INTEGER NOT NULL DEFAULT 0"
                    )
                )
            await connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_manga_group_key ON manga (group_key)")
            )
            await connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_manga_url_slug ON manga (url_slug)")
            )
            await connection.execute(
                text(
                    "UPDATE manga SET group_key = 'manga-' || id "
                    "WHERE group_key IS NULL OR group_key = ''"
                )
            )
            await connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_manga_visible_group "
                    "ON manga (group_key) WHERE has_chapters = 1"
                )
            )
            await connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_manga_visible_chapters_group "
                    "ON manga (chapters_count, group_key) WHERE has_chapters = 1"
                )
            )
            await connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_manga_search_pending "
                    "ON manga (search_indexed) WHERE search_indexed = 0"
                )
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
                text("CREATE INDEX IF NOT EXISTS ix_manga_rating_count ON manga (rating_count)")
            )
            await connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_manga_chapters_count "
                    "ON manga (chapters_count)"
                )
            )
            await connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_manga_created_at ON manga (created_at)")
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
            await connection.execute(
                text("ALTER TABLE manga ADD COLUMN IF NOT EXISTS url_slug VARCHAR(255)")
            )
            await connection.execute(
                text(
                    "ALTER TABLE manga ADD COLUMN IF NOT EXISTS "
                    "has_chapters BOOLEAN NOT NULL DEFAULT FALSE"
                )
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
                    "search_indexed BOOLEAN NOT NULL DEFAULT FALSE"
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
                text("CREATE INDEX IF NOT EXISTS ix_manga_url_slug ON manga (url_slug)")
            )
            await connection.execute(
                text(
                    "UPDATE manga SET group_key = 'manga-' || replace(id::text, '-', '') "
                    "WHERE group_key IS NULL OR group_key = ''"
                )
            )
            await connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_manga_visible_group "
                    "ON manga (group_key) WHERE has_chapters"
                )
            )
            await connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_manga_visible_chapters_group "
                    "ON manga (chapters_count, group_key) WHERE has_chapters"
                )
            )
            await connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_manga_status_key ON manga (status_key)")
            )
            await connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_manga_search_pending "
                    "ON manga (search_indexed) WHERE search_indexed = false"
                )
            )
            await connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_manga_last_synced_at ON manga (last_synced_at)")
            )
            await connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_manga_rating_count ON manga (rating_count)")
            )
            await connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_manga_chapters_count "
                    "ON manga (chapters_count)"
                )
            )
            await connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_manga_created_at ON manga (created_at)")
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

        # Rows that already carry a normalized document from a previous v1.2
        # deploy are marked indexed in one cheap statement.  Everything else
        # is handled by the background worker; startup must never walk 78k
        # rows in Python and hold the SQLite write lock for minutes.
        if dialect == "sqlite":
            await connection.execute(
                text(
                    "UPDATE manga SET search_indexed = 1 "
                    "WHERE search_indexed = 0 AND search_blob <> ''"
                )
            )
            # Repair visibility once per card-table version.  The first
            # statement fixes stale true flags after chapter cleanup; the
            # second only probes the handful of source summaries that claim
            # chapters but never received chapter rows (20 rows in production).
            state_version = (
                await connection.execute(
                    text("SELECT cards_version FROM catalog_state WHERE id = 1")
                )
            ).scalar()
            if state_version != CATALOG_CARDS_VERSION:
                await connection.execute(
                    text(
                        "UPDATE manga SET has_chapters = 0 "
                        "WHERE has_chapters = 1 "
                        "AND NOT EXISTS (SELECT 1 FROM chapters "
                        "WHERE chapters.manga_id = manga.id)"
                    )
                )
                await connection.execute(
                    text(
                        "UPDATE manga SET has_chapters = 1 "
                        "WHERE has_chapters = 0 AND chapters_count > 0 "
                        "AND EXISTS (SELECT 1 FROM chapters "
                        "WHERE chapters.manga_id = manga.id)"
                    )
                )
        else:
            await connection.execute(
                text(
                    "UPDATE manga SET search_indexed = true "
                    "WHERE search_indexed = false AND search_blob <> ''"
                )
            )
            state_version = (
                await connection.execute(
                    text("SELECT cards_version FROM catalog_state WHERE id = 1")
                )
            ).scalar()
            if state_version != CATALOG_CARDS_VERSION:
                await connection.execute(
                    text(
                        "UPDATE manga SET has_chapters = false "
                        "WHERE has_chapters AND NOT EXISTS "
                        "(SELECT 1 FROM chapters WHERE chapters.manga_id = manga.id)"
                    )
                )
                await connection.execute(
                    text(
                        "UPDATE manga SET has_chapters = true "
                        "WHERE NOT has_chapters AND chapters_count > 0 AND EXISTS "
                        "(SELECT 1 FROM chapters WHERE chapters.manga_id = manga.id)"
                    )
                )

    # Build the small canonical card table once.  The window function runs over
    # manga rows only; it never joins the 1.7M chapter table, and the result is
    # ~19k rows in production.  Subsequent imports update a single group.
    factory = create_session_factory(engine)
    async with factory() as session:
        rebuilt, did_rebuild = await ensure_catalog_groups(session)
        await session.commit()
    logger.info(
        "catalogue runtime schema is up to date (%s cards, rebuilt=%s)",
        rebuilt,
        did_rebuild,
    )
