from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from manga_common.auth import create_access_token
from manga_common.config import get_settings
from manga_common.errors import AppError, app_error_handler
from services.gateway.app.config import GatewaySettings
from services.gateway.app.notifications_api import router

USER = "11111111-1111-4111-8111-111111111111"
MANGA = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
VARIANT = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


class FakeComments:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def follows(self, headers):
        self.calls.append(("follows", headers))
        return []

    async def follow(self, payload, headers):
        self.calls.append(("follow", payload))
        return {
            **payload,
            "created_at": "2026-01-01T00:00:00Z",
        }

    async def unfollow(self, manga_id, headers):
        self.calls.append(("unfollow", manga_id))
        return {"ok": True}

    async def follow_status(self, manga_id, headers):
        return {"manga_id": manga_id, "following": True}

    async def notification_settings(self, headers):
        return {
            "in_app_enabled": True,
            "web_push_enabled": True,
            "max_pushes_per_hour": 5,
            "quiet_hours_start": None,
            "quiet_hours_end": None,
            "updated_at": "2026-01-01T00:00:00Z",
        }

    async def save_notification_settings(self, payload, headers):
        self.calls.append(("settings", payload))
        return {**payload, "updated_at": "2026-01-01T00:00:00Z"}


class FakeCatalog:
    async def variants(self, manga_id: str):
        return SimpleNamespace(
            items=[SimpleNamespace(id=uuid.UUID(MANGA)), SimpleNamespace(id=uuid.UUID(VARIANT))]
        )


class FakeNotifier:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def push_config(self):
        return {"enabled": True, "public_key": "public-key", "reason": None}

    async def subscribe(self, **kwargs):
        self.calls.append(("subscribe", kwargs))
        return {"subscribed": True}

    async def unsubscribe(self, **kwargs):
        self.calls.append(("unsubscribe", kwargs))
        return {"unsubscribed": True}

    async def status(self, user_id):
        self.calls.append(("status", user_id))
        return {"subscribed": True, "count": 1, "endpoints": []}


def make_client() -> tuple[TestClient, FakeComments, FakeNotifier]:
    settings = GatewaySettings(
        _env_file=None,
        service_name="gateway-test",
        environment="test",
        jwt_secret="gateway-test-secret",
        internal_token="gateway-internal",
        log_level="WARNING",
        log_json=False,
    )
    comments = FakeComments()
    notifier = FakeNotifier()
    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.include_router(router)
    app.state.comments = comments
    app.state.notifier = notifier
    app.state.catalog = FakeCatalog()
    app.dependency_overrides[get_settings] = lambda: settings
    token, _ = create_access_token(settings, subject=USER, role="user")
    client = TestClient(app, headers={"Authorization": f"Bearer {token}"})
    return client, comments, notifier


def test_follow_routes_include_variant_ids() -> None:
    client, comments, _ = make_client()
    response = client.post(
        "/api/v1/notifications/follows",
        json={
            "manga_id": MANGA,
            "manga_title": "Тайтл",
            "poster_url": "https://cdn.example/p.jpg",
            "source": "mangapoisk",
        },
    )
    assert response.status_code == 200, response.text
    follow_call = next(call for call in comments.calls if call[0] == "follow")
    assert follow_call[1]["variant_ids"] == [MANGA, VARIANT]
    assert follow_call[1]["manga_title"] == "Тайтл"

    status = client.get(f"/api/v1/notifications/follows/{MANGA}")
    assert status.json() == {"manga_id": MANGA, "following": True}
    removed = client.delete(f"/api/v1/notifications/follows/{MANGA}")
    assert removed.status_code == 200
    assert removed.json()["message"]


def test_settings_validation_and_proxy() -> None:
    client, comments, _ = make_client()
    loaded = client.get("/api/v1/notifications/settings")
    assert loaded.status_code == 200

    invalid = client.put(
        "/api/v1/notifications/settings",
        json={"quiet_hours_start": 22},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "invalid_quiet_hours"

    valid = client.put(
        "/api/v1/notifications/settings",
        json={
            "in_app_enabled": True,
            "web_push_enabled": True,
            "max_pushes_per_hour": 3,
            "quiet_hours_start": 22,
            "quiet_hours_end": 8,
        },
    )
    assert valid.status_code == 200
    saved = next(call for call in comments.calls if call[0] == "settings")
    assert saved[1]["max_pushes_per_hour"] == 3


def test_push_config_is_public_and_subscription_requires_auth() -> None:
    client, _, notifier = make_client()
    config = TestClient(client.app).get("/api/v1/notifications/push/config")
    assert config.status_code == 200
    assert config.json()["public_key"] == "public-key"

    anonymous = TestClient(client.app).post(
        "/api/v1/notifications/push/subscribe",
        json={
            "endpoint": "https://fcm.googleapis.com/fcm/send/abc",
            "keys": {"p256dh": "p", "auth": "a"},
        },
    )
    assert anonymous.status_code == 401

    subscribed = client.post(
        "/api/v1/notifications/push/subscribe",
        json={
            "endpoint": "https://fcm.googleapis.com/fcm/send/abc",
            "keys": {"p256dh": "p", "auth": "a"},
        },
    )
    assert subscribed.status_code == 200
    call = notifier.calls[-1]
    assert call[0] == "subscribe"
    assert call[1]["user_id"] == USER
    assert call[1]["p256dh"] == "p"

    status = client.get("/api/v1/notifications/push/status")
    assert status.json()["subscribed"] is True
