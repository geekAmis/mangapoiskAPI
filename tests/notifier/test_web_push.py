from __future__ import annotations

import base64
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient
from manga_common.config import get_settings
from py_vapid import Vapid
from services.notifier.app.config import NotifierSettings
from services.notifier.app.main import create_app
from services.notifier.app.push import PushDeliveryError, PywebpushSender

INTERNAL_TOKEN = "notifier-test-token"
USER = "11111111-1111-4111-8111-111111111111"
OTHER_USER = "22222222-2222-4222-8222-222222222222"
MANGA = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
CHAPTER_1 = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
CHAPTER_2 = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
ENDPOINT = "https://push.example.test/sub/device-1"
FIXED_NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


class FakeSender:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error: Exception | None = None

    async def __call__(self, subscription, payload):  # type: ignore[no-untyped-def]
        self.calls.append({"subscription": subscription, "payload": payload})
        if self.error is not None:
            raise self.error


def make_client(
    db_path: Path,
    *,
    sender: FakeSender | None = None,
    configured: bool = True,
    **overrides: object,
) -> TestClient:
    values: dict[str, object] = {
        "service_name": "notifier-test",
        "environment": "test",
        "log_level": "WARNING",
        "log_json": False,
        "notifier_database_url": f"sqlite+aiosqlite:///{db_path.as_posix()}",
        "internal_token": INTERNAL_TOKEN,
        "jwt_secret": "notifier-test-jwt-secret",
        "web_push_enabled": configured,
        "vapid_public_key": "test-public-key" if configured else None,
        "vapid_private_key": "test-private-key" if configured else None,
        "push_endpoint_allowed_hosts": "push.example.test",
        "push_max_per_hour": 10,
    }
    values.update(overrides)
    settings = NotifierSettings(_env_file=None, **values)  # type: ignore[arg-type]
    app = create_app(
        settings,
        sender=sender or FakeSender(),
        clock=lambda: FIXED_NOW,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def headers() -> dict[str, str]:
    return {"X-Internal-Token": INTERNAL_TOKEN}


def subscribe(
    client: TestClient,
    *,
    user_id: str = USER,
    endpoint: str = ENDPOINT,
    p256dh: str = "p256dh-key",
    auth: str = "auth-key",
):
    return client.post(
        "/internal/push/subscribe",
        json={
            "user_id": user_id,
            "endpoint": endpoint,
            "keys": {"p256dh": p256dh, "auth": auth},
            "user_agent": "pytest",
        },
        headers=headers(),
    )


def push(
    client: TestClient,
    *,
    chapters: list[tuple[str, str]] | None = None,
    recipients: list[dict[str, Any]] | None = None,
    manga: str = MANGA,
):
    chapters = chapters or [(CHAPTER_1, "Глава 1")]
    return client.post(
        "/internal/push/chapters",
        json={
            "events": [
                {
                    "manga_id": manga,
                    "chapter_id": chapter_id,
                    "manga_title": "Тестовый тайтл",
                    "chapter_label": label,
                    "source": "mangapoisk",
                }
                for chapter_id, label in chapters
            ],
            "recipients": recipients
            if recipients is not None
            else [{"user_id": USER, "max_pushes_per_hour": 5}],
        },
        headers=headers(),
    )


def test_config_and_subscription_lifecycle(tmp_path: Path) -> None:
    with make_client(tmp_path / "subs.db") as client:
        config = client.get("/internal/push/public-key", headers=headers())
        assert config.status_code == 200
        assert config.json()["enabled"] is True
        assert config.json()["public_key"] == "test-public-key"

        created = subscribe(client)
        assert created.status_code == 200, created.text
        assert created.json()["subscribed"] is True
        status = client.get(
            "/internal/push/status", params={"user_id": USER}, headers=headers()
        ).json()
        assert status["subscribed"] is True
        assert status["count"] == 1
        assert status["endpoints"][0]["host"] == "push.example.test"

        # Re-subscribing the same endpoint is idempotent, not a second device.
        assert subscribe(client).status_code == 200
        assert (
            client.get("/internal/push/status", params={"user_id": USER}, headers=headers())
            .json()["count"]
            == 1
        )

        removed = client.request(
            "DELETE",
            "/internal/push/subscribe",
            json={"user_id": USER, "endpoint": ENDPOINT},
            headers=headers(),
        )
        assert removed.status_code == 200
        assert removed.json()["unsubscribed"] is True
        assert (
            client.get("/internal/push/status", params={"user_id": USER}, headers=headers())
            .json()["subscribed"]
            is False
        )


def test_push_payload_delivery_and_idempotency(tmp_path: Path) -> None:
    sender = FakeSender()
    with make_client(tmp_path / "push.db", sender=sender) as client:
        subscribe(client)
        first = push(client)
        assert first.status_code == 200, first.text
        assert first.json()["sent"] == 1
        assert first.json()["deliveries"] == 1
        assert len(sender.calls) == 1

        payload = sender.calls[0]["payload"]
        assert payload["title"] == "Новая глава — Тестовый тайтл"
        assert payload["body"] == "Глава 1"
        assert payload["tag"] == f"chapter-{MANGA}"
        assert payload["data"] == {
            "type": "chapter",
            "manga_id": MANGA,
            "chapter_ids": [CHAPTER_1],
            "url": f"/reader/{CHAPTER_1}",
        }
        subscription = sender.calls[0]["subscription"]
        assert subscription["endpoint"] == ENDPOINT
        assert subscription["keys"] == {"p256dh": "p256dh-key", "auth": "auth-key"}

        repeat = push(client)
        assert repeat.status_code == 200
        assert repeat.json()["sent"] == 0
        assert repeat.json()["deduped"] == 1
        assert len(sender.calls) == 1

        # Duplicate events inside one payload collapse to one delivery.
        duplicate_events = push(
            client,
            chapters=[(CHAPTER_2, "Глава 2"), (CHAPTER_2, "Глава 2")],
        )
        assert duplicate_events.json()["sent"] == 1
        assert len(sender.calls) == 2
        assert len(sender.calls[1]["payload"]["data"]["chapter_ids"]) == 1


def test_batches_multiple_chapters_per_title_into_one_push(tmp_path: Path) -> None:
    sender = FakeSender()
    with make_client(tmp_path / "batch.db", sender=sender) as client:
        subscribe(client)
        response = push(
            client,
            chapters=[(CHAPTER_1, "Глава 1"), (CHAPTER_2, "Глава 2")],
        )
        assert response.status_code == 200
        assert response.json()["sent"] == 1
        assert response.json()["deliveries"] == 1  # one device
        assert len(sender.calls) == 1
        payload = sender.calls[0]["payload"]
        assert payload["title"] == "Новые главы — Тестовый тайтл"
        assert "2 главы" in payload["body"]
        assert payload["data"]["chapter_ids"] == [CHAPTER_1, CHAPTER_2]
        assert payload["data"]["url"] == f"/reader/{CHAPTER_1}"


def test_rate_limit_skips_push_but_does_not_touch_other_users(tmp_path: Path) -> None:
    sender = FakeSender()
    with make_client(tmp_path / "rate.db", sender=sender) as client:
        subscribe(client)
        subscribe(client, user_id=OTHER_USER, endpoint="https://push.example.test/sub/device-2")
        recipient = [{"user_id": USER, "max_pushes_per_hour": 1}]
        first = push(client, chapters=[(CHAPTER_1, "Глава 1")], recipients=recipient)
        assert first.json()["sent"] == 1
        second = push(client, chapters=[(CHAPTER_2, "Глава 2")], recipients=recipient)
        assert second.json()["sent"] == 0
        assert second.json()["skipped"] == 1
        assert second.json()["reasons"]["rate_limited"] == 1
        assert len(sender.calls) == 1

        other = push(
            client,
            chapters=[(CHAPTER_2, "Глава 2")],
            recipients=[{"user_id": OTHER_USER, "max_pushes_per_hour": 1}],
        )
        assert other.json()["sent"] == 1


def test_quiet_hours_skip_only_push(tmp_path: Path) -> None:
    sender = FakeSender()
    with make_client(tmp_path / "quiet.db", sender=sender) as client:
        subscribe(client)
        response = push(
            client,
            recipients=[
                {
                    "user_id": USER,
                    "max_pushes_per_hour": 5,
                    "quiet_hours_start": 12,
                    "quiet_hours_end": 13,
                }
            ],
        )
        assert response.status_code == 200
        assert response.json()["sent"] == 0
        assert response.json()["skipped"] == 1
        assert response.json()["reasons"]["quiet_hours"] == 1
        assert sender.calls == []


def test_no_subscription_is_reported_not_failed(tmp_path: Path) -> None:
    with make_client(tmp_path / "nosub.db") as client:
        response = push(client)
        assert response.status_code == 200
        assert response.json()["sent"] == 0
        assert response.json()["reasons"]["no_subscription"] == 1


def test_unsubscribe_stops_future_pushes(tmp_path: Path) -> None:
    sender = FakeSender()
    with make_client(tmp_path / "unsub.db", sender=sender) as client:
        subscribe(client)
        assert push(client).json()["sent"] == 1
        assert subscribe(client).status_code == 200
        client.request(
            "DELETE",
            "/internal/push/subscribe",
            json={"user_id": USER, "endpoint": ENDPOINT},
            headers=headers(),
        )
        result = push(client, chapters=[(CHAPTER_2, "Глава 2")]).json()
        assert result["sent"] == 0
        assert result["reasons"]["no_subscription"] == 1
        assert len(sender.calls) == 1


def test_gone_subscription_is_deactivated(tmp_path: Path) -> None:
    sender = FakeSender()
    sender.error = PushDeliveryError("410 Gone", gone=True)
    with make_client(tmp_path / "gone.db", sender=sender) as client:
        subscribe(client)
        result = push(client).json()
        assert result["sent"] == 0
        assert result["failed"] == 1
        status = client.get(
            "/internal/push/status", params={"user_id": USER}, headers=headers()
        ).json()
        assert status["count"] == 0


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://push.example.test/sub/1",
        "https://evil.example/sub/1",
        "https://127.0.0.1/sub/1",
        "https://localhost/sub/1",
    ],
)
def test_endpoint_validation_rejects_ssrf_targets(tmp_path: Path, endpoint: str) -> None:
    with make_client(tmp_path / "ssrf.db") as client:
        response = subscribe(client, endpoint=endpoint)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_push_subscription"


def test_unconfigured_push_returns_no_delivery(tmp_path: Path) -> None:
    sender = FakeSender()
    with make_client(tmp_path / "unconfigured.db", sender=sender, configured=False) as client:
        config = client.get("/internal/push/public-key", headers=headers()).json()
        assert config["enabled"] is False
        assert config["public_key"] is None
        response = push(client)
        assert response.status_code == 200
        assert response.json()["sent"] == 0
        assert response.json()["reasons"]["not_configured"] == 1
        assert sender.calls == []


def test_payload_url_falls_back_to_reader_path(tmp_path: Path) -> None:
    sender = FakeSender()
    with make_client(tmp_path / "url.db", sender=sender) as client:
        subscribe(client)
        assert client.post(
            "/internal/push/chapters",
            json={
                "events": [
                    {
                        "manga_id": MANGA,
                        "chapter_id": CHAPTER_1,
                        "manga_title": "Тайтл",
                        "chapter_label": "Глава 1",
                        "chapter_url": "https://source.example/chapter",
                    }
                ],
                "recipients": [{"user_id": USER}],
            },
            headers=headers(),
        ).status_code == 200
        assert sender.calls[0]["payload"]["data"]["url"] == f"/reader/{CHAPTER_1}"


def test_vapid_raw_key_is_decoded_from_base64url() -> None:
    vapid = Vapid()
    vapid.generate_keys()
    private = base64.urlsafe_b64encode(
        vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
    ).rstrip(b"=").decode()
    public = base64.urlsafe_b64encode(
        vapid.public_key.public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint,
        )
    ).rstrip(b"=").decode()
    settings = NotifierSettings(
        _env_file=None,
        service_name="notifier-test",
        environment="test",
        vapid_private_key=private,
        vapid_public_key=public,
    )
    sender = PywebpushSender(settings)
    parsed = sender._vapid()
    assert parsed.private_key is not None
    assert sender.settings.vapid_public_key == public


def test_internal_token_is_required(tmp_path: Path) -> None:
    with make_client(tmp_path / "token.db") as client:
        assert client.get("/internal/push/public-key").status_code == 401
        response = client.post(
            "/internal/push/subscribe",
            json={
                "user_id": USER,
                "endpoint": ENDPOINT,
                "keys": {"p256dh": "p", "auth": "a"},
            },
        )
        assert response.status_code == 401
