from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from manga_common.db import create_all, create_engine, create_session_factory
from manga_common.source_models import ChapterSummary, MangaDetail
from services.catalog.app.config import CatalogSettings
from services.catalog.app.repository import find_manga_by_source
from services.catalog.app.service import CatalogService
from services.comments.app.auth import CommentUser
from services.comments.app.config import CommentsSettings
from services.comments.app.schemas import ChapterEventIn, FollowCreate, NotificationSettingsIn
from services.comments.app.service import CommentsService
from services.notifier.app.config import NotifierSettings
from services.notifier.app.push import PushService

USER_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
FIXED_NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def detail(chapter_numbers: list[int]) -> MangaDetail:
    return MangaDetail(
        source="mangapoisk",
        source_id="real-title",
        slug="real-title",
        title="Реальный тайтл",
        description="Описание",
        poster_url="https://cdn.example/poster.jpg",
        genres=["Фэнтези"],
        chapters=[
            ChapterSummary(
                source="mangapoisk",
                source_id=f"real-title-{number}",
                manga_source_id="real-title",
                number=str(number),
                title=f"Глава {number}",
                published_at=datetime(2026, 1, number, tzinfo=UTC),
            )
            for number in chapter_numbers
        ],
    )


class ParserStub:
    def __init__(self) -> None:
        self.next_detail = detail([1])
        self.calls = 0

    async def manga(self, source: str, *, source_id: str | None = None, url: str | None = None):
        self.calls += 1
        return self.next_detail


class FakePush:
    def __init__(self, service: PushService) -> None:
        self.service = service
        self.calls: list[dict[str, Any]] = []

    async def dispatch_chapters(self, events, recipients):  # type: ignore[no-untyped-def]
        self.calls.append({"events": events, "recipients": recipients})
        return await self.service.send_chapters(events=events, recipients=recipients)

    async def close(self) -> None:
        return None


class RecordingSender:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, subscription, payload):  # type: ignore[no-untyped-def]
        self.calls.append({"subscription": subscription, "payload": payload})


@pytest.mark.asyncio
async def test_real_catalog_import_produces_exactly_one_notification(
    tmp_path: Path,
) -> None:
    # --- real catalog import -------------------------------------------------
    catalog_settings = CatalogSettings(
        _env_file=None,
        service_name="catalog-test",
        environment="test",
        catalog_database_url=(
            f"sqlite+aiosqlite:///{(tmp_path / 'catalog.db').as_posix()}"
        ),
    )
    catalog_engine = create_engine(catalog_settings.catalog_dsn)
    await create_all(catalog_engine)
    catalog_factory = create_session_factory(catalog_engine)
    parser = ParserStub()
    catalog = CatalogService(catalog_settings, catalog_factory, parser)  # type: ignore[arg-type]

    initial = await catalog.import_detail(detail([1]))
    assert initial.imported_chapters == 1
    # Simulate an already known title whose next scheduled refresh discovers a
    # genuinely new chapter from the source.
    async with catalog_factory() as session:
        manga = await find_manga_by_source(session, "mangapoisk", "real-title")
        assert manga is not None
        manga.last_synced_at = datetime.now(UTC) - timedelta(days=1)
        manga_id = manga.id
        await session.commit()

    parser.next_detail = detail([1, 2])
    refresh = await catalog.refresh_stale(limit=1)
    assert refresh.refreshed == 1
    assert len(refresh.new_chapters) == 1
    event = refresh.new_chapters[0]
    assert event.chapter_label == "Глава 2"
    assert event.manga_id == manga_id
    # import_detail() was fed a parsed detail directly; refresh_stale() is the
    # one real parser call that discovered chapter 2.
    assert parser.calls == 1
    await catalog_engine.dispose()

    # --- notifier transport with an injected sender (no production push) -----
    notifier_settings = NotifierSettings(
        _env_file=None,
        service_name="notifier-test",
        environment="test",
        notifier_database_url=(
            f"sqlite+aiosqlite:///{(tmp_path / 'notifier.db').as_posix()}"
        ),
        web_push_enabled=True,
        vapid_public_key="test-public",
        vapid_private_key="test-private",
        push_endpoint_allowed_hosts="push.example.test",
        log_level="WARNING",
        log_json=False,
    )
    notifier_engine = create_engine(notifier_settings.notifier_dsn)
    await create_all(notifier_engine)
    notifier_factory = create_session_factory(notifier_engine)
    sender = RecordingSender()
    push_service = PushService(
        notifier_settings,
        notifier_factory,
        sender=sender,
        clock=lambda: FIXED_NOW,
    )
    await push_service.subscribe(
        user_id=USER_ID,
        endpoint="https://push.example.test/sub/real",
        p256dh="p256dh",
        auth="auth",
    )

    # --- comments follow + fan-out ------------------------------------------
    comments_settings = CommentsSettings(
        _env_file=None,
        service_name="comments-test",
        environment="test",
        comments_database_url=(
            f"sqlite+aiosqlite:///{(tmp_path / 'comments.db').as_posix()}"
        ),
        chapter_notifications_push_enabled=True,
        log_level="WARNING",
        log_json=False,
    )
    comments_engine = create_engine(comments_settings.comments_dsn)
    await create_all(comments_engine)
    comments_factory = create_session_factory(comments_engine)
    fake_push = FakePush(push_service)
    comments = CommentsService(comments_settings, comments_factory, fake_push)
    viewer = CommentUser(id=USER_ID, name="Reader")
    await comments.follow_title(
        viewer,
        FollowCreate(
            manga_id=manga_id,
            manga_title="Реальный тайтл",
            poster_url="https://cdn.example/poster.jpg",
            source="mangapoisk",
            variant_ids=[manga_id],
        ),
    )
    await comments.save_settings(
        viewer,
        NotificationSettingsIn(
            in_app_enabled=True,
            web_push_enabled=True,
            max_pushes_per_hour=5,
        ),
    )

    chapter_event = ChapterEventIn(
        manga_id=event.manga_id,
        chapter_id=event.chapter_id,
        manga_title=event.manga_title,
        chapter_label=event.chapter_label,
        source=event.source,
    )
    first = await comments.fanout_chapters([chapter_event])
    assert first.created == 1
    assert first.followers == 1
    assert first.push_recipients == 1
    assert first.push is not None and first.push["sent"] == 1

    feed = await comments.list_notifications(
        viewer, unread_only=False, page=1, limit=20
    )
    assert feed.total == 1
    assert feed.unread_count == 1
    assert feed.items[0].type == "chapter"
    assert feed.items[0].chapter is not None
    assert feed.items[0].chapter.chapter_id == event.chapter_id
    assert feed.items[0].chapter.chapter_label == "Глава 2"
    assert len(sender.calls) == 1
    payload = sender.calls[0]["payload"]
    assert payload["data"]["chapter_ids"] == [str(event.chapter_id)]
    assert payload["data"]["url"] == f"/reader/{event.chapter_id}"

    # A scheduler retry or a second import pass must not duplicate either
    # channel.  The second fan-out still asks the notifier, whose delivery
    # marker rejects the chapter.
    second = await comments.fanout_chapters([chapter_event])
    assert second.created == 0
    assert second.followers == 1
    assert second.push is not None
    assert second.push["sent"] == 0
    assert second.push["deduped"] == 1
    assert len(sender.calls) == 1
    feed_again = await comments.list_notifications(
        viewer, unread_only=False, page=1, limit=20
    )
    assert feed_again.total == 1

    await comments_engine.dispose()
    await notifier_engine.dispose()
