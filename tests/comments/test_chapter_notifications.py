from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from .test_comments_api import (
    ADMIN,
    INTERNAL_TOKEN,
    MANGA,
    OTHER_MANGA,
    USER_A,
    USER_B,
    headers,
    make_client,
)

CHAPTER = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
OTHER_CHAPTER = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"


class FakeDispatcher:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def dispatch_chapters(self, events, recipients):  # type: ignore[no-untyped-def]
        self.calls.append({"events": list(events), "recipients": list(recipients)})
        return {"configured": True, "sent": 1, "skipped": 0, "failed": 0}

    async def close(self) -> None:
        return None


def attach(client: TestClient) -> FakeDispatcher:
    dispatcher = FakeDispatcher()
    client.app.state.service.push_dispatcher = dispatcher
    return dispatcher


def follow(
    client: TestClient,
    *,
    user_id: str = USER_A,
    manga: str = MANGA,
    title: str = "Тестовый тайтл",
    variants: list[str] | None = None,
):
    return client.post(
        "/internal/follows",
        json={
            "manga_id": manga,
            "manga_title": title,
            "poster_url": "https://cdn.example/poster.jpg",
            "source": "mangapoisk",
            "variant_ids": variants or [],
        },
        headers=headers(user_id),
    )


def fanout(client: TestClient, *, manga: str = MANGA, chapter: str = CHAPTER):
    return client.post(
        "/internal/notifications/chapters",
        json={
            "events": [
                {
                    "manga_id": manga,
                    "chapter_id": chapter,
                    "manga_title": "Тестовый тайтл",
                    "chapter_label": "Глава 42",
                    "source": "mangapoisk",
                }
            ]
        },
        headers={"X-Internal-Token": INTERNAL_TOKEN},
    )


def test_follow_unfollow_list_and_variant_status(tmp_path: Path) -> None:
    with make_client(tmp_path / "follows.db") as client:
        attach(client)
        first = follow(client, variants=[OTHER_MANGA])
        assert first.status_code == 200, first.text
        assert first.json()["manga_title"] == "Тестовый тайтл"

        duplicate = follow(
            client,
            title="Тестовый тайтл (обновлено)",
            variants=[OTHER_MANGA, "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"],
        )
        assert duplicate.status_code == 200
        assert duplicate.json()["manga_title"] == "Тестовый тайтл (обновлено)"

        listing = client.get("/internal/follows", headers=headers(USER_A))
        assert listing.status_code == 200
        assert len(listing.json()) == 1
        assert listing.json()[0]["manga_id"] == MANGA

        assert (
            client.get(f"/internal/follows/{MANGA}", headers=headers(USER_A))
            .json()["following"]
            is True
        )
        # The variant id resolves to the same title subscription.
        assert (
            client.get(f"/internal/follows/{OTHER_MANGA}", headers=headers(USER_A))
            .json()["following"]
            is True
        )
        assert (
            client.get(f"/internal/follows/{MANGA}", headers=headers(USER_B))
            .json()["following"]
            is False
        )

        removed = client.delete(f"/internal/follows/{MANGA}", headers=headers(USER_A))
        assert removed.status_code == 200
        assert removed.json() == {"ok": True}
        assert client.get("/internal/follows", headers=headers(USER_A)).json() == []
        assert (
            client.get(f"/internal/follows/{OTHER_MANGA}", headers=headers(USER_A))
            .json()["following"]
            is False
        )


def test_notification_settings_defaults_and_roundtrip(tmp_path: Path) -> None:
    with make_client(tmp_path / "settings.db") as client:
        attach(client)
        default = client.get(
            "/internal/notifications/settings", headers=headers(USER_A)
        )
        assert default.status_code == 200
        assert default.json()["in_app_enabled"] is True
        assert default.json()["web_push_enabled"] is True
        assert default.json()["max_pushes_per_hour"] == 5
        assert default.json()["quiet_hours_start"] is None

        saved = client.put(
            "/internal/notifications/settings",
            json={
                "in_app_enabled": False,
                "web_push_enabled": True,
                "max_pushes_per_hour": 2,
                "quiet_hours_start": 22,
                "quiet_hours_end": 8,
            },
            headers=headers(USER_A),
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["in_app_enabled"] is False
        assert saved.json()["max_pushes_per_hour"] == 2
        loaded = client.get(
            "/internal/notifications/settings", headers=headers(USER_A)
        )
        assert loaded.json()["quiet_hours_start"] == 22
        assert loaded.json()["quiet_hours_end"] == 8

        invalid = client.put(
            "/internal/notifications/settings",
            json={"quiet_hours_start": 22},
            headers=headers(USER_A),
        )
        assert invalid.status_code == 422


def test_fanout_is_deduplicated_and_resolves_variants(tmp_path: Path) -> None:
    with make_client(tmp_path / "fanout.db") as client:
        dispatcher = attach(client)
        assert follow(client, variants=[OTHER_MANGA]).status_code == 200
        assert follow(client, user_id=USER_B, manga=OTHER_MANGA).status_code == 200

        first = fanout(client, manga=OTHER_MANGA)
        assert first.status_code == 200, first.text
        payload = first.json()
        assert payload["created"] == 2
        assert payload["followers"] == 2  # A via alias + B directly
        assert payload["push_recipients"] == 2
        assert len(dispatcher.calls) == 1
        assert len(dispatcher.calls[0]["recipients"]) == 2

        second = fanout(client, manga=OTHER_MANGA)
        assert second.status_code == 200
        assert second.json()["created"] == 0

        feed_a = client.get(
            "/internal/notifications",
            params={"unread_only": "true"},
            headers=headers(USER_A),
        ).json()
        assert feed_a["total"] == 1
        chapter = feed_a["items"][0]
        assert chapter["type"] == "chapter"
        assert chapter["comment_id"] is None
        assert chapter["chapter"]["manga_id"] == MANGA
        assert chapter["chapter"]["chapter_id"] == CHAPTER
        assert chapter["chapter"]["chapter_label"] == "Глава 42"
        assert chapter["chapter"]["url"] == f"/reader/{CHAPTER}"

        feed_b = client.get(
            "/internal/notifications", headers=headers(USER_B)
        ).json()
        assert feed_b["total"] == 1


def test_channel_settings_control_in_app_and_push(tmp_path: Path) -> None:
    with make_client(tmp_path / "channels.db") as client:
        dispatcher = attach(client)
        follow(client, user_id=USER_A)
        follow(client, user_id=USER_B)
        client.put(
            "/internal/notifications/settings",
            json={
                "in_app_enabled": False,
                "web_push_enabled": True,
                "max_pushes_per_hour": 5,
            },
            headers=headers(USER_A),
        )
        client.put(
            "/internal/notifications/settings",
            json={
                "in_app_enabled": True,
                "web_push_enabled": False,
                "max_pushes_per_hour": 5,
            },
            headers=headers(USER_B),
        )

        result = fanout(client, manga=MANGA).json()
        assert result["created"] == 1  # only B has in-app enabled
        assert result["push_recipients"] == 1  # only A has push enabled
        recipients = dispatcher.calls[0]["recipients"]
        assert [item["user_id"] for item in recipients] == [USER_A]

        assert (
            client.get("/internal/notifications", headers=headers(USER_A)).json()["total"]
            == 0
        )
        assert (
            client.get("/internal/notifications", headers=headers(USER_B)).json()["total"]
            == 1
        )


def test_merged_feed_and_read_state_across_channels(tmp_path: Path) -> None:
    with make_client(tmp_path / "merged.db") as client:
        attach(client)
        follow(client)
        root = client.post(
            f"/internal/manga/{MANGA}/comments",
            json={"body": "Комментарий"},
            headers=headers(USER_A),
        ).json()
        reply = client.post(
            f"/internal/manga/{MANGA}/comments",
            json={"body": "Ответ", "parent_id": root["id"]},
            headers=headers(USER_B),
        )
        assert reply.status_code == 201
        assert fanout(client).json()["created"] == 1

        feed = client.get("/internal/notifications", headers=headers(USER_A)).json()
        assert feed["total"] == 2
        assert feed["unread_count"] == 2
        assert {item["type"] for item in feed["items"]} == {"reply", "chapter"}

        marked = client.post(
            "/internal/notifications/read",
            json={"ids": [item["id"] for item in feed["items"]]},
            headers=headers(USER_A),
        )
        assert marked.status_code == 200
        assert marked.json()["updated"] == 2
        assert (
            client.get("/internal/notifications", headers=headers(USER_A))
            .json()["unread_count"]
            == 0
        )

        rejected = client.post(
            "/internal/notifications/read",
            json={"ids": [item["id"] for item in feed["items"]]},
            headers=headers(USER_B),
        )
        assert rejected.json()["updated"] == 0


def test_unfollow_stops_fanout_immediately(tmp_path: Path) -> None:
    with make_client(tmp_path / "unfollow.db") as client:
        attach(client)
        follow(client)
        assert client.delete(f"/internal/follows/{MANGA}", headers=headers(USER_A)).status_code == 200
        result = fanout(client).json()
        assert result == {
            "created": 0,
            "followers": 0,
            "push_recipients": 0,
            "push": None,
        }


def test_follow_requires_authentication(tmp_path: Path) -> None:
    with make_client(tmp_path / "auth.db") as client:
        attach(client)
        response = client.post(
            "/internal/follows",
            json={"manga_id": MANGA, "manga_title": "Тайтл"},
            headers={"X-Internal-Token": INTERNAL_TOKEN},
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "missing_user"


def test_admin_follow_data_is_not_exposed(tmp_path: Path) -> None:
    with make_client(tmp_path / "admin.db") as client:
        attach(client)
        follow(client, user_id=USER_A)
        assert (
            client.get("/internal/follows", headers=headers(ADMIN, "Admin", "admin"))
            .json()
            == []
        )


@pytest.mark.parametrize("chapter_id", [str(uuid.uuid4())])
def test_arbitrary_chapter_ids_are_deduped(tmp_path: Path, chapter_id: str) -> None:
    with make_client(tmp_path / f"{chapter_id}.db") as client:
        attach(client)
        follow(client)
        for _ in range(3):
            response = fanout(client, chapter=chapter_id)
            assert response.status_code == 200
        feed = client.get("/internal/notifications", headers=headers(USER_A)).json()
        assert feed["total"] == 1
