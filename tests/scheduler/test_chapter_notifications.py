from __future__ import annotations

from typing import Any

import httpx
import pytest

from .test_catalogue_import import close, make_scheduler


@pytest.mark.asyncio
async def test_refresh_fans_out_new_chapters_to_in_app_and_telegram(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/internal/maintenance/refresh":
            return httpx.Response(
                200,
                json={
                    "refreshed": 1,
                    "failed": 0,
                    "errors": [],
                    "new_chapters": [
                        {
                            "manga_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                            "manga_title": "Реальный тайтл",
                            "chapter_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
                            "chapter_label": "Глава 42",
                            "source": "mangapoisk",
                            "url": "https://source.example/chapter-42",
                            "published_at": "2026-01-01T12:00:00Z",
                        }
                    ],
                },
            )
        body = None
        if request.content:
            body = request.read().decode("utf-8")
        calls.append({"path": path, "body": body})
        if path == "/internal/notify/new-chapters":
            return httpx.Response(200, json={"sent": True})
        if path == "/internal/notifications/chapters":
            return httpx.Response(
                200,
                json={
                    "created": 1,
                    "followers": 1,
                    "push_recipients": 1,
                    "push": {"sent": 1},
                },
            )
        return httpx.Response(404, json={"error": {"message": "not found"}})

    scheduler = make_scheduler(
        monkeypatch,
        handler,
        comments_url="http://comments.test",
        notifier_url="http://notifier.test",
        public_web_url="https://web.test",
    )
    try:
        await scheduler.refresh()
    finally:
        await close(scheduler)

    paths = [call["path"] for call in calls]
    assert paths == [
        "/internal/notify/new-chapters",
        "/internal/notifications/chapters",
    ]

    import json

    fanout = json.loads(calls[1]["body"])
    assert len(fanout["events"]) == 1
    event = fanout["events"][0]
    assert event["manga_id"] == "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    assert event["chapter_id"] == "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    assert event["manga_title"] == "Реальный тайтл"
    assert event["chapter_label"] == "Глава 42"
    assert event["source"] == "mangapoisk"
    assert event["chapter_url"] is None


@pytest.mark.asyncio
async def test_refresh_skips_fanout_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/internal/maintenance/refresh":
            return httpx.Response(
                200,
                json={
                    "refreshed": 1,
                    "failed": 0,
                    "errors": [],
                    "new_chapters": [
                        {
                            "manga_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                            "manga_title": "Тайтл",
                            "chapter_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
                            "chapter_label": "Глава 1",
                            "source": "mangapoisk",
                        }
                    ],
                },
            )
        return httpx.Response(200, json={"sent": True})

    scheduler = make_scheduler(
        monkeypatch,
        handler,
        chapter_notifications_enabled=False,
        notify_new_chapters=False,
        comments_url="http://comments.test",
    )
    try:
        await scheduler.refresh()
    finally:
        await close(scheduler)
    assert calls == ["/internal/maintenance/refresh"]
