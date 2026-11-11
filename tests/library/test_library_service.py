from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from manga_common.db import create_all, create_engine, create_session_factory
from manga_common.errors import ConflictError, UnauthorizedError
from manga_common.schemas import ReaderSettings
from services.library.app.config import LibrarySettings
from services.library.app.service import LibraryService


@pytest.mark.asyncio
async def test_library_auth_bookmarks_progress(tmp_path: Path) -> None:
    db_path = tmp_path / "library.db"
    settings = LibrarySettings(
        service_name="library-test",
        library_database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
        jwt_secret="library-test-secret",
    )
    engine = create_engine(settings.library_dsn)
    session_factory = create_session_factory(engine)
    await create_all(engine)
    service = LibraryService(settings, session_factory)

    tokens = await service.register(
        email="reader@example.com",
        password="very-secret-password",
        display_name="Читатель",
    )
    assert tokens.user.email == "reader@example.com"
    assert tokens.access_token

    with pytest.raises(ConflictError):
        await service.register(
            email="reader@example.com", password="another-password", display_name="Другой"
        )

    login = await service.login(email="reader@example.com", password="very-secret-password")
    assert login.user.display_name == "Читатель"
    with pytest.raises(UnauthorizedError):
        await service.login(email="reader@example.com", password="wrong")

    rotated = await service.refresh(login.refresh_token)
    assert rotated.refresh_token != login.refresh_token
    with pytest.raises(UnauthorizedError):
        await service.refresh(login.refresh_token)

    user_id = rotated.user.id
    manga_id = uuid.uuid4()
    chapter_id = uuid.uuid4()

    bookmark = await service.add_bookmark(user_id, manga_id)
    assert bookmark.manga_id == manga_id
    bookmarks = await service.bookmarks(user_id)
    assert len(bookmarks) == 1
    assert await service.remove_bookmark(user_id, manga_id)
    assert await service.bookmarks(user_id) == []

    progress = await service.upsert_progress(
        user_id, manga_id=manga_id, chapter_id=chapter_id, page=5, total_pages=20
    )
    assert progress.page == 5
    history = await service.history(user_id)
    assert len(history) == 1
    assert history[0].chapter_id == chapter_id

    settings_value = ReaderSettings(theme="paper", reader_mode="horizontal", auto_scroll=True)
    saved = await service.save_reader_settings(user_id, settings_value)
    assert saved.theme == "paper"
    loaded = await service.reader_settings(user_id)
    assert loaded.reader_mode == "horizontal"

    await service.logout(rotated.refresh_token)
    await engine.dispose()
