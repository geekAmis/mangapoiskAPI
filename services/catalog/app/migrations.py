from __future__ import annotations

import logging

from manga_common.db import Base
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine

from .models import Manga
from .normalization import genres_key, status_key

logger = logging.getLogger(__name__)


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
                text(
                    "CREATE INDEX IF NOT EXISTS ix_manga_last_synced_at ON manga (last_synced_at)"
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

        # Backfill filter keys.  Genres used to be indexed by their raw source
        # label; the canonical English slug table changed that, so recompute
        # only rows whose stored key differs.
        rows = (
            await connection.execute(
                select(Manga.id, Manga.status, Manga.genres, Manga.genres_key, Manga.status_key)
            )
        ).all()
        updated = 0
        for row in rows:
            expected_genres = genres_key(row.genres or [])
            expected_status = status_key(row.status)
            if row.genres_key != expected_genres or row.status_key != expected_status:
                await connection.execute(
                    update(Manga)
                    .where(Manga.id == row.id)
                    .values(genres_key=expected_genres, status_key=expected_status)
                )
                updated += 1
        if updated:
            logger.info("backfilled canonical filter keys for %s catalogue entries", updated)

        # Covers created before grouping support need the denormalised key.
        await connection.execute(
            text(
                "UPDATE manga_covers SET group_key = "
                "(SELECT group_key FROM manga WHERE manga.id = manga_covers.manga_id) "
                "WHERE group_key IS NULL"
            )
        )

    logger.info("catalogue runtime schema is up to date")
