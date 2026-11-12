from __future__ import annotations

import logging

from manga_common.db import Base
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


async def ensure_runtime_schema(engine: AsyncEngine) -> None:
    """Idempotent additive migration for existing library databases."""

    dialect = engine.dialect.name
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        if dialect == "sqlite":
            result = await connection.execute(text("PRAGMA table_info(users)"))
            columns = {row[1] for row in result.fetchall()}
            if "age_confirmed_at" not in columns:
                await connection.execute(
                    text("ALTER TABLE users ADD COLUMN age_confirmed_at DATETIME")
                )
        else:
            await connection.execute(
                text(
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
                    "age_confirmed_at TIMESTAMPTZ"
                )
            )
    logger.info("library runtime schema is up to date")
