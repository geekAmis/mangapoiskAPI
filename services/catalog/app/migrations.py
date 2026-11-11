from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def ensure_runtime_schema(engine: AsyncEngine) -> None:
    """Additive migrations for existing SQLite/Postgres databases.

    ``create_all`` creates new tables but never new columns.  The project keeps
    a tiny forward-only migration here so an existing deployed catalogue does
    not need a full Alembic setup for these additive fields.
    """

    dialect = engine.dialect.name
    async with engine.begin() as connection:
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
                await connection.execute(text("ALTER TABLE manga ADD COLUMN group_key VARCHAR(255)"))
            await connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_manga_group_key ON manga (group_key)")
            )
        else:
            await connection.execute(
                text("ALTER TABLE chapters ADD COLUMN IF NOT EXISTS translator VARCHAR(255)")
            )
            await connection.execute(
                text("ALTER TABLE manga ADD COLUMN IF NOT EXISTS group_key VARCHAR(255)")
            )
            await connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_manga_group_key ON manga (group_key)")
            )
    logger.info("catalogue runtime schema is up to date")
