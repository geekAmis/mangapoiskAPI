from __future__ import annotations

from pathlib import Path

import pytest
from manga_common.db import create_engine, create_session_factory
from services.library.app.config import LibrarySettings
from services.library.app.migrations import ensure_runtime_schema
from services.library.app.service import LibraryService
from sqlalchemy import text


def _settings(db_path: Path) -> LibrarySettings:
    return LibrarySettings(
        service_name="library-age-test",
        library_database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
        jwt_secret="library-age-test-secret",
    )


@pytest.mark.asyncio
async def test_age_confirmation_and_revoke(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "library.db")
    engine = create_engine(settings.library_dsn)
    session_factory = create_session_factory(engine)
    await ensure_runtime_schema(engine)
    service = LibraryService(settings, session_factory)

    tokens = await service.register(
        email="adult@example.com",
        password="very-secret-password",
        display_name="Взрослый",
    )
    user_id = tokens.user.id
    assert tokens.user.age_confirmed_at is None

    status = await service.age_status(user_id)
    assert status.age_confirmed is False

    confirmed = await service.confirm_age(user_id)
    assert confirmed.age_confirmed is True
    assert confirmed.age_confirmed_at is not None

    me = await service.me(user_id)
    assert me.age_confirmed_at is not None

    # Confirmation is idempotent and keeps the original date.
    again = await service.confirm_age(user_id)
    assert again.age_confirmed_at == confirmed.age_confirmed_at

    revoked = await service.revoke_age(user_id)
    assert revoked.age_confirmed is False
    assert revoked.age_confirmed_at is None
    assert (await service.me(user_id)).age_confirmed_at is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_runtime_migration_adds_age_column_to_legacy_users(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "legacy.db")
    engine = create_engine(settings.library_dsn)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "CREATE TABLE users ("
                "id VARCHAR(32) PRIMARY KEY, email VARCHAR(320) NOT NULL, "
                "password_hash VARCHAR(255) NOT NULL, display_name VARCHAR(64) NOT NULL, "
                "role VARCHAR(32) NOT NULL, is_active BOOLEAN NOT NULL, "
                "created_at DATETIME, updated_at DATETIME)"
            )
        )

    await ensure_runtime_schema(engine)
    async with engine.begin() as connection:
        result = await connection.execute(text("PRAGMA table_info(users)"))
        columns = {row[1] for row in result.fetchall()}
    assert "age_confirmed_at" in columns
    await engine.dispose()
