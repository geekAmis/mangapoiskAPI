from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def ensure_runtime_schema(engine: AsyncEngine) -> None:
    """Apply additive, idempotent schema changes for existing databases.

    ``Base.metadata.create_all`` only creates missing tables; it never adds a
    column to a deployed ``users`` table.  This forward-only migration adds the
    Yandex OAuth columns and the unique index without touching existing rows.
    It is safe to run on every startup and on both SQLite and PostgreSQL.
    """

    async with engine.begin() as connection:
        dialect = connection.dialect.name
        if dialect == "sqlite":
            rows = (await connection.execute(text("PRAGMA table_info(users)"))).fetchall()
            columns = {row[1] for row in rows}
            if not columns:
                # A fresh database is fully created by create_all(); nothing to
                # migrate.  Never run ALTER on a missing table.
                return
            if "yandex_id" not in columns:
                await connection.execute(text("ALTER TABLE users ADD COLUMN yandex_id VARCHAR(64)"))
            if "auth_provider" not in columns:
                await connection.execute(
                    text(
                        "ALTER TABLE users ADD COLUMN auth_provider VARCHAR(32) "
                        "NOT NULL DEFAULT 'password'"
                    )
                )
            await connection.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_yandex_id ON users (yandex_id)")
            )
        else:
            await connection.execute(
                text("ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS yandex_id VARCHAR(64)")
            )
            await connection.execute(
                text(
                    "ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS auth_provider "
                    "VARCHAR(32) NOT NULL DEFAULT 'password'"
                )
            )
            await connection.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_yandex_id ON users (yandex_id)")
            )
    logger.info("library runtime schema is up to date")
