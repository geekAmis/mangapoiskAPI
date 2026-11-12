from __future__ import annotations

from pathlib import Path

import pytest
from manga_common.db import create_all, create_engine
from services.library.app.migrations import ensure_runtime_schema
from sqlalchemy import text


@pytest.mark.asyncio
async def test_runtime_migration_adds_yandex_columns_idempotently(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+aiosqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                CREATE TABLE users (
                    id CHAR(32) PRIMARY KEY,
                    email VARCHAR(320) NOT NULL UNIQUE,
                    password_hash VARCHAR(255) NOT NULL,
                    display_name VARCHAR(64) NOT NULL,
                    role VARCHAR(32) NOT NULL,
                    is_active BOOLEAN NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
        await connection.execute(
            text(
                "INSERT INTO users VALUES "
                "('00000000000000000000000000000001', 'old@example.com', 'hash', "
                "'Старый', 'user', 1, '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
        )

    await ensure_runtime_schema(engine)
    await ensure_runtime_schema(engine)

    async with engine.connect() as connection:
        columns = {
            row[1]
            for row in (await connection.execute(text("PRAGMA table_info(users)"))).fetchall()
        }
        row = (
            await connection.execute(
                text("SELECT email, yandex_id, auth_provider FROM users")
            )
        ).one()
        indexes = {
            item[1]
            for item in (
                await connection.execute(text("PRAGMA index_list(users)"))
            ).fetchall()
        }

    assert {"yandex_id", "auth_provider"} <= columns
    assert row == ("old@example.com", None, "password")
    assert "ix_users_yandex_id" in indexes
    await engine.dispose()


@pytest.mark.asyncio
async def test_fresh_database_has_yandex_schema(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+aiosqlite:///{(tmp_path / 'fresh.db').as_posix()}")
    await create_all(engine)
    await ensure_runtime_schema(engine)

    async with engine.connect() as connection:
        columns = {
            row[1]
            for row in (await connection.execute(text("PRAGMA table_info(users)"))).fetchall()
        }
        tables = {
            row[0]
            for row in (
                await connection.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                )
            ).fetchall()
        }

    assert {"yandex_id", "auth_provider"} <= columns
    assert {"oauth_states", "oauth_handoff_codes"} <= tables
    await engine.dispose()
